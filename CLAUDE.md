# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Everything runs in Docker — do not install or run Python/Bun tooling on the host. `./run.ps1 start|stop [-Prod]` starts/stops the stack (dev by default) and waits for health. Directly, use the dev override:

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

Settings live in `app/core/config.py` (pydantic-settings, env prefix `EPUB_`). `EPUB_ENCRYPTION_KEY` encrypts provider API keys stored in SQLite. There is a single data directory: the repo-root `data/`, mounted at `/data` (`EPUB_DATA_DIR`); uploads, translated output and the DB all derive from it. Never mount anything under `/app` in compose besides the source itself, or Docker recreates host directories inside `backend/`.

Provider bootstrap (`app/core/bootstrap.py`, run on startup): API keys come from the repo-root `.env`, mounted as a file at `EPUB_ENV_FILE` (not via compose `env_file`, since names like `OPENAI-API-KEY` are not valid env vars; names are normalized). `config.yaml` (mounted at `/config/config.yaml`) declares providers upserted by name; one whose `api_key_env` is missing is skipped. The dev defaults are `openrouter-free` (free, heavily rate-limited), `openai-cheap` (`gpt-4.1-nano`, paid — use sparingly) and `fake`. `ProviderConfig.source` is `config` for bootstrapped rows and `user` for rows created or edited via the API (`POST`/`PUT /api/providers`); bootstrap never takes over a `user` row with the same name (editing a config provider in the UI therefore detaches it from `config.yaml`). Tests point both files to nonexistent paths.

## Architecture

Monorepo: `backend/` (FastAPI + LangChain/LangGraph + async SQLAlchemy/aiosqlite) and `frontend/` (React 19 + Vite + Tailwind v4 + Zustand + react-router).

**Translation flow** — the core of the app, spans several layers:

1. `app/services/job_runner.py`: jobs run as server tasks, independent of any client. Every start goes through the queue (`QueueItem` table, one book at a time by `position`).
   - **Starting**: the translate page's start is `enqueue([book], front=True)`. `POST /api/queue` appends several books with one `RunConfig` and `keep_glossary`; that flag copies the previous queued book's glossary (`JobStore.import_glossary`) when the next book starts.
   - **Running**: `run_job` builds the LLM(s) and the `TranslationPipeline` and loads the resume checkpoint (`JobStore.prepare`). It stores the full `RunConfig` on the `TranslationJob` (returned as `config` by `/progress`), then consumes `translate_document`. Each event is first persisted (`JobStore.handle`), then published to subscribers. Final messages (`job_complete`, `cancelled`) are published only after the DB update.
   - **Stopping and failures**: stop (WS `{"action": "stop"}`, `POST /api/translate/{id}/stop`, `POST /api/queue/stop`) pauses the running book and halts the queue. A failed book is recorded and the queue moves on.
   - **Restarts**: on startup a `running` item becomes `paused` and waits for `POST /api/queue/start`. "Start over" (`restart`) applies once.
   - **WebSocket**: `app/api/websocket.py` (`/ws/translate/{book_id}`) is protocol only: `start` or `watch`, then it streams the book's messages until the job is over. A disconnect only stops following; the job goes on.
2. `app/services/translation_service.py` (`translate_document`): format-agnostic orchestrator. It runs the analysis (skipped when `Book.analysis` exists), then translates units (chapters/pages) as concurrent tasks bounded by `max_concurrency`, merging their events through a queue. Completed units are skipped (`chapter_skipped`); others resume from their per-block checkpoint. Finally `doc.save` writes the output. On cancel it still drains the already-finished checkpoints.
3. `app/services/documents.py`: `Document` adapters (`EpubDocument`, `PdfDocument`; `open_document(path)` picks by suffix). A unit = chapter or PDF page = list of blocks; translations are always `list[str | None]` per unit (None = keep original). `save` writes the same format as the input. The end of the previous unit is passed as `lead_context` (PDF sentences continue across pages).
4. `app/services/job_store.py`: the persistence layer for resume.
   - `chunk_done` → `Chapter.block_translations` slice
   - `chapter_saved` → full list, `translated_html` and chapter status
   - `glossary_update` and `analysis_complete` are saved immediately
   - `prepare(restart=True)` wipes progress but keeps user-edited glossary entries
   - `recover_interrupted_jobs()` (startup) turns `translating` into `paused`
5. `app/agents/pipeline.py`: `translate_chapter(blocks, previous=...)` chunks the blocks deterministically and runs only the chunks with missing blocks through a LangGraph `StateGraph`: translate → review (optional) → retry with the reviewer's feedback | finalize → `chunk_done`. A failed chunk leaves its blocks `None` (reported in `failed_chunks`) instead of storing the source as translated. The shared `Glossary` (`app/agents/glossary.py`) is read live by all nodes. It validates model-proposed `new_terms` (they must occur in the source and never override existing/user entries), sends only relevant entries in prompts, and does a deterministic `enforce` pass.
6. Blocks and alignment: `html_processor.extract_html_blocks` is the single source of blocks for both `SmartChunker.extract_blocks` and `replace_text_blocks`, so translation `i` always lands on block `i`. Inline tags travel as numbered placeholders (`<1>…</1>`, `<2/>`) and are restored with their attributes. `translate_blocks` enforces one output paragraph per block (retry, then per-block fallback). Never change block extraction in only one place.
7. Agents (`analyzer.py`, `translator_agent.py`, `reviewer.py`) use `structured_chain` against Pydantic models in `app/models/schemas.py`. `FakeChatModel` overrides `with_structured_output` by schema type, so a new structured schema must also be handled there.

**PDF** (`app/services/pdf_service.py`, PyMuPDF): the output must keep the input's layout, changing only the language.

- **Extraction**: blocks are PyMuPDF text blocks. Word-processor continuation blocks (e.g. a drop-cap line) are merged. Spans whose style differs from the block's dominant one become placeholders.
- **Saving**: the original glyphs of translated blocks are redacted while images and line art are kept. Consecutive paragraphs of one column/font become a *region*, typeset as one HTML flow with `insert_htmlbox` and the original margins, indents, alignment and line height.
- **Room and font size**: a region may grow into 60% of the free space below it. Regions with the same font size on a page share one scale.
- **Fonts**: metric-compatible substitutes (Carlito for Calibri, Caladea for Cambria, Liberation for Arial/Times/Courier). They are copied *without GSUB* at image build (`scripts/strip_ligatures.py`), because MuPDF writes unusable ToUnicode entries for ligatures, which would break copy/search.
- **Limits**: scanned PDFs (no text layer) are rejected, and text drawn as images stays untranslated.

Progress events are forwarded to the client as `{"event": event_type, chapter_index, total_chapters, chunk_index, total_chunks, message, data, ts}` (bulky `translations`/`translated_html` stripped). `src/hooks/useTranslationWs.ts` keeps the raw events (newest first). `src/lib/jobEvents.ts` derives the live chunks (`liveChunks`, using `chunk_translated.data.source_text`/`translated_text` and the review events) and the activity rows (`logEntries`). Event names are a contract with that file.

**Frontend design system**:
- **Tokens**: CSS variables in `src/index.css`, exposed as Tailwind colors via `@theme inline`: `paper`, `surface`, `tint`, `ink`, `muted`, `faint`, `line`, `accent`, `warn`, `danger`, `violet`. `.dark` swaps the values. Use these, never raw grays.
- **Fonts**: `font-serif` (Newsreader) for headings and numbers; Inter for the UI; `font-mono` for model ids.
- **Primitives**: `components/ui.tsx` (`Button`, `Card`, `Page`, `Heading`, `StatusPill`) and `lib/styles.ts` (`buttonClass`, `inputClass`; non-component exports live outside `.tsx` because of react-refresh).
- **Model and provider pickers**: `ModelCombobox` and `ProviderSelect` (Headless UI). `ProviderLogo` (brand marks from `@lobehub/icons-static-svg`, picked from provider type, OpenRouter URL or `vendor/model` prefix).
- **Visual checks**: Chrome automation may be unavailable. Instead, take screenshots with Playwright in Docker (`mcr.microsoft.com/playwright`) on the `epub_translator_default` network, using the frontend container's IP (the Vite dev server only accepts localhost/IP hosts). Book statuses: `uploaded`, `translating`, `paused` (resumable), `completed`, `failed` (finished with incomplete units or crashed; also resumable).

New DB columns are added automatically by `init_db` (`ALTER TABLE ADD COLUMN` for missing nullable columns); anything more complex needs a real migration.

**LLM providers** (`app/core/llm_factory.py`): `create_llm(LLMConfig)` switches on `provider` (openai, anthropic, ollama, custom OpenAI-compatible, fake). Provider configs are DB rows (`ProviderConfig`) managed via REST in `app/api/routes.py` and by the bootstrap. Resilience is layered:
- a client-side `InMemoryRateLimiter` (`requests_per_second`)
- SDK retries with backoff on 429/5xx (`llm_max_retries`)
- `structured_chain(prompt, llm, Schema)`, which every agent must use instead of `llm.with_structured_output`. It applies the provider's `structured_output_method` (stored in `llm.metadata`) and retries the whole call `chain_retries` times.

Defaults live in `Settings`, `config.yaml` `translation:` overrides them at startup, and a provider's `params` overrides them per job. Reasoning models (`gpt-5*`, `o*`) are created without `temperature`.

**REST** (`app/api/routes.py`, mounted at `/api`): providers CRUD (incl. `PUT`), book upload/list/download/preview/estimate/progress, glossary editing, queue (`/queue`: list, add, start, stop, remove, clear finished). `GET /books/{id}/progress` returns the run state (completed/failed/in-flight units, ETA) plus `recent_events`, an in-memory ring buffer (200, newest first) of the WS messages kept in `services/job_runner.py`, so a reload still shows the recent log; every WS message carries a server `ts`. Frontend calls go through `src/lib/api.ts`.

**Cost estimates** (`GET /api/books/{id}/estimate`, shown on the upload page by `components/CostEstimate.tsx`):
- **Prices** (`services/pricing.py`): OpenAI and Anthropic chat-model prices come from LiteLLM's public price list. They are cached in `data/pricing_cache.json` for `pricing_refresh_hours`; if the download fails, the stale cache is used, then `app/data/pricing_fallback.json`. Refresh that bundled snapshot with `scripts/snapshot_prices.py`. Tests run offline: `EPUB_PRICING_URL=""` selects the snapshot.
- **Token profile** (`services/cost_estimator.py`): `profile_document` walks the book's real chunks. It reuses `translation_service.analysis_text`/`lead_context_for`, so it counts what the pipeline actually sends. The profile is cached in `Book.token_profile`.
- **Prompt sizes**: `usage` measures the real prompt templates. Approximations (target-language expansion, rejection rate, Claude tokenizer factor, thinking tokens) are module constants.
- **Model rules** (`llm_factory`): `thinks_by_default` and `accepts_temperature` decide which models are billed for thinking (OpenAI reasoning models, Claude ≥ 5) and which get `temperature` (Claude Opus 4.7+ / 5.x reject it with a 400).
- **Model list**: `config.yaml` `pricing.models`, plus the default models of configured providers. With `provider_id` + `model` the endpoint estimates just that model.

**Model picker** (`GET /api/providers/{id}/models`; `POST /api/providers/models` for a provider not saved yet, also a key check, `services/model_catalog.py`, `components/ModelPicker.tsx`): models are listed live from the provider's API.
- **How each provider is listed**: OpenAI and Anthropic through their official SDKs; OpenAI-compatible routers such as OpenRouter through the OpenAI SDK with `base_url` (their listing includes prices); Ollama via `/api/tags` at the provider's `base_url` or `ollama_base_url` (default `http://host.docker.internal:11434`: the host seen from the container; `extra_hosts: host-gateway` in compose for Linux), with a readable "Ollama is not running at …" error.
- **Filtering**: OpenAI's list is reduced to chat models usable with chat completions; embeddings, audio, image, `-pro` and dated snapshots that have an alias are dropped.
- **Prices**: `price_for` maps router names (`openai/gpt-4.1-mini`, `*:free`) to known prices.
- **Caching**: 10 minutes per provider configuration.
- **Fallbacks**: in the UI, a failed listing falls back to a free-text model id. `default_model` is only the preselection.
