# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Everything runs in Docker — do not install or run Python/Bun tooling on the host. Use the dev override:

```bash
DC="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
$DC up --build                                    # backend :8000 (uvicorn --reload), frontend :3000 (Vite)
$DC run --rm backend <cmd>                        # any backend command, e.g. python scripts/make_sample_epub.py
$DC run --rm backend uv add <pkg>                 # add a dependency (updates pyproject.toml + uv.lock), then rebuild
$DC run --rm frontend bun run lint                # frontend lint
```

`./format.ps1` runs isort → black → ruff `--fix` and eslint + tsc inside the containers. Line length is 100 for all Python tools.

Production: `docker compose up --build` (backend `prod` target, nginx frontend).

Tests (pytest, `asyncio_mode=auto`, no network by default):

```bash
$DC run --rm --no-deps backend pytest                                   # whole suite
$DC run --rm --no-deps backend pytest tests/test_pipeline.py::test_name # single test
$DC run --rm --no-deps backend pytest -m live                           # real-provider smoke tests (cost quota)
```

`tests/conftest.py` points `EPUB_DATA_DIR` to a temp dir before importing `app`, and provides `ScriptedLLM` (a `FakeChatModel` with per-schema `handlers`, `fail` error injection, `calls_for(schema)` and concurrency `peak`), a `sample_epub` fixture and a `db` fixture that recreates the schema. In the running app, a provider of type `fake` (`app/core/fake_llm.py`) gives deterministic "BAU … MIAO" translations without any API.

## Configuration

Settings live in `app/core/config.py` (pydantic-settings, env prefix `EPUB_`). `EPUB_ENCRYPTION_KEY` encrypts provider API keys stored in SQLite. There is a single data directory: the repo-root `data/`, mounted at `/data` (`EPUB_DATA_DIR`); uploads, translated output and the DB all derive from it. Never mount anything under `/app` in compose besides the source itself, or Docker recreates host directories inside `backend/`. Schema is created with `Base.metadata.create_all` on startup; there are no migrations, so model changes need a DB reset or manual ALTER.

## Architecture

Monorepo: `backend/` (FastAPI + LangChain/LangGraph + async SQLAlchemy/aiosqlite) and `frontend/` (React 19 + Vite + Tailwind v4 + Zustand + react-router).

**Translation flow** — the core of the app, spans several layers:

1. `app/api/websocket.py` (`/ws/translate/{book_id}`): client sends `{"action": "start", provider_id, model, source_language, target_language, ...}`. The handler loads provider/book/glossary from DB, decrypts the API key, builds the LLM via `create_llm`, creates a `TranslationPipeline`, and registers it in `active_jobs` for cancellation. A concurrent listener task handles `{"action": "stop"}` and disconnects by calling `pipeline.cancel()`. On completion it persists per-chapter translated HTML (`Chapter.translated_html`, used by the Preview page), the merged glossary, and book status.
2. `app/services/epub_service.py` (`EpubService.translate_book`): async generator that iterates EPUB document items, extracts text blocks, drives the pipeline per chapter, rebuilds HTML via `html_processor.replace_text_blocks`/`normalize_epub_html`, writes the output EPUB, and yields `TranslationProgress` events (`chapter_saved` carries HTML, `job_complete` carries `output_path`).
3. `app/agents/pipeline.py`: `TranslationPipeline` owns the running glossary and runs `analyze_context` (analyzer agent → genre/tone/glossary seeds) then a compiled LangGraph `StateGraph` per chapter (`build_chapter_graph`): translate → review → (retry | finalize) → next chunk/complete. Nodes emit progress through `get_stream_writer()`; the wrapper re-yields them as `TranslationProgress`. `_enforce_glossary` does a deterministic regex pass afterward to replace any source terms the LLM left untranslated.
4. Agents (`analyzer.py`, `translator_agent.py`, `reviewer.py`) use `llm.with_structured_output(...)` against Pydantic models in `app/models/schemas.py` (`AnalysisResult`, `TranslationResult`, `GlossaryItem`). `FakeChatModel` overrides `with_structured_output` by schema type, so a new structured schema must also be handled there.
5. `app/services/chunker.py` (`SmartChunker`): paragraph-boundary chunking by estimated token count (tiktoken only if `use_tiktoken=True`; configured in the websocket handler: target 600, max 1000, 2-block overlap); overlap blocks become `context_text`, not re-translated.

Progress events are forwarded to the client as `{"event": event_type, chapter_index, total_chapters, chunk_index, total_chunks, message, data}`; the frontend consumes them in `src/hooks/useTranslationWs.ts` and stores them in the Zustand store (`src/stores/appStore.ts`). Event names are a contract between `pipeline.py`/`epub_service.py`/`websocket.py` and that hook.

**LLM providers** (`app/core/llm_factory.py`): `create_llm(LLMConfig)` switches on `provider` (openai, anthropic, ollama, custom OpenAI-compatible, fake). Provider configs are DB rows (`ProviderConfig`) managed via REST in `app/api/routes.py`.

**REST** (`app/api/routes.py`, mounted at `/api`): providers CRUD, book upload/list/download/preview, glossary editing. Frontend calls go through `src/lib/api.ts`.
