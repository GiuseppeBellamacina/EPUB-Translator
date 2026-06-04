# EPUB Translator

Intelligent EPUB translation tool with a modern React UI and an agentic translation engine that maintains terminology consistency across your entire book.

## Features

- **Agentic Translation Pipeline**: Context Analyzer → Translator → Reviewer (3-agent system)
- **Glossary Consistency**: Auto-generated glossary maintained across all chapters, editable by the user
- **Smart Chunking**: Hybrid paragraph + sliding window chunking with context overlap
- **Multi-Provider LLM**: OpenAI, Anthropic, Ollama, or any OpenAI-compatible API
- **Real-time Progress**: WebSocket-based live updates per chapter and chunk
- **Side-by-Side Preview**: Compare original vs translated text
- **Translation History**: Track all translated books with re-download capability
- **Spacing Fix**: Post-processing eliminates excessive whitespace in rebuilt EPUBs
- **Deployable**: Docker Compose setup (frontend + backend)

## Architecture

```
├── frontend/       # React + Vite + TailwindCSS (Bun)
├── backend/        # FastAPI + LangChain + SQLite
│   ├── agents/     # Analyzer, Translator, Reviewer
│   ├── services/   # Chunker, EPUB, HTML processor
│   └── api/        # REST + WebSocket endpoints
└── docker-compose.yml
```

## Quick Start

### Development (local)

**Backend:**

```bash
cd backend
uv sync
cp .env.example .env    # Edit with your encryption key
uv run uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
bun install
bun run dev
```

Open http://localhost:3000

### Docker

```bash
docker compose up --build
```

Frontend at http://localhost:3000, Backend at http://localhost:8000

## Usage

1. **Settings** → Add an LLM provider (OpenAI API key, Ollama URL, etc.)
2. **Upload** → Drag & drop your EPUB file
3. **Configure** → Select provider, model, languages
4. **Translate** → Watch real-time progress, edit glossary if needed
5. **Preview** → Side-by-side comparison of original vs translated
6. **Download** → Get your translated EPUB

## Translation Pipeline

```
EPUB Upload
  → Context Analysis (genre, tone, characters, key terms)
  → Auto-generate Glossary
  → Per Chapter:
      → Smart Chunking (paragraph boundaries, 600 token target, 2-block overlap)
      → Translate (glossary-aware, context-aware)
      → Review (consistency check, glossary violations)
      → Retry if issues found
  → Rebuild EPUB (spacing-normalized HTML)
  → Validate & Save
```

## Supported Providers

| Provider  | Type  | Notes                                                     |
| --------- | ----- | --------------------------------------------------------- |
| OpenAI    | Cloud | GPT-4o, GPT-4o-mini, etc.                                 |
| Anthropic | Cloud | Claude 3.5, Claude 4, etc.                                |
| Ollama    | Local | Any model (llama3, mistral, etc.)                         |
| Custom    | Any   | Any OpenAI-compatible endpoint (vLLM, LMStudio, Together) |

## Requirements

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- Bun 1.0+ (or Node.js 18+)
- Docker (optional, for deployment)
