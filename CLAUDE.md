# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAG (Retrieval-Augmented Generation) chatbot backend for GaramPosTech (가람포스텍) technical support. Built with **FastAPI + PostgreSQL (pgvector) + LangChain + OpenAI**.

Primary language: **Python 3.12**. All code comments and domain terms are in Korean.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (port 5002, no hot-reload by default)
python main.py
# Or with hot-reload:
RELOAD=1 python main.py

# Run via uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 5002

# Database migrations
alembic upgrade head                              # Apply all migrations
alembic revision --autogenerate -m "description"  # Generate new migration
```

No test suite or linter is configured.

## Environment

All config is loaded from `.env` via `core/config.py`. Key variables:
- `DB_USER`, `DB_PASSWORD`, `DB_SERVER`, `DB_PORT`, `DB_NAME` — PostgreSQL connection
- `OPENAI_API` — OpenAI API key (used for embeddings and LLM)
- `FRIENDLI_API` — Friendli EXAONE endpoint key
- `CLOVA_STT_ID`, `CLOVA_STT_SECRET` — Naver CLOVA Speech-to-Text
- `LLM_PROVIDER` (default: `openai`), `LLM_MODEL` (default: `gpt-4o-mini`)
- `EMBEDDING_MODEL` (default: `text-embedding-3-small`), dimension: 1536
- `UPLOAD_FOLDER` (default: `./file`) — uploaded document storage
- `HOST`, `PORT`, `RELOAD` — uvicorn server settings

## Architecture

### Layer Structure

```
main.py                  → FastAPI app, CORS, lifespan (APScheduler)
app/routers.py           → Registers all endpoint routers
app/endpoints/           → API route handlers (thin layer, delegates to crud/service)
schemas/                 → Pydantic request/response models
crud/                    → Database queries (SQLAlchemy)
service/                 → Business logic (LLM orchestration, upload pipeline, retrieval)
models/                  → SQLAlchemy ORM models
database/                → Engine, session, Alembic migrations
core/                    → Config, pricing tables, scheduler, utilities
langchain_service/       → LangChain integration (chains, embeddings, LLM setup, prompts)
LANGUAGE/                → Localization (ko/en) for prompts and few-shot examples
```

Endpoints follow a consistent pattern: `app/endpoints/<domain>.py` → `crud/<domain>.py` → `models/<domain>.py` with `schemas/<domain>.py` for validation. The `service/` layer handles cross-cutting logic (LLM calls, retrieval, upload processing).

### RAG Pipeline

1. **Upload** (`service/upload_pipeline.py`): PDF → PyMuPDF extraction → URL normalization (garampos.co.kr links) → parent-child chunking (900 chars, 150 overlap) → OpenAI embedding → store in `knowledge_chunk` with pgvector
2. **Retrieval** (`service/knowledge_retrieval.py`): Hybrid search combining pgvector cosine similarity (100 candidates) + pg_trgm trigram matching (50 candidates), merged by chunk ID with heuristic ranking
3. **QA Chain** (`langchain_service/chain/qa_chain.py`): Retrieved context → few-shot prompt → LLM → structured output with `[SOURCES]` section, STATUS/REASON_CODE/CITATIONS metadata

### Key Database Details

- PostgreSQL with `pgvector` extension (1536-dim vectors) and `pg_trgm` for trigram similarity
- IVFFlat index (lists=100, cosine ops) on `knowledge_chunk.vector_memory`
- `knowledge` → `knowledge_page` → `knowledge_chunk` (document → page → chunk hierarchy)
- `chat_session` → `message` (with vector_memory), `feedback`, insight tables for analytics
- API cost tracking in `api_cost` table (USD, 6 decimal precision)

### Background Jobs

APScheduler runs daily (00:05 KST) and hourly (:05) dashboard rollups. Initialized in `main.py` lifespan, configured in `core/scheduler.py`.

### WebSocket

`/ws/notifications?admin_id=X` for real-time admin notifications. Connection manager in `service/ws_manager.py`.

### Domain-Specific Patterns

- **Alias expansion**: Embeddings include alias pairs (POS ↔ 포스) configured via `EMBED_ALIAS_MAP`
- **URL repair**: Upload pipeline fixes corrupted `garampos.co.kr` URLs from PDF extraction
- **Category classification**: Rule-based keyword matching in `service/llm_service.py` with fallback to "etc/기타"
- **Cost tracking**: Token-level cost calculation for LLM, embedding, and STT (CLOVA billed per 6-second unit, KRW→USD)

## API Routes

All routes registered at root `/` via `app/routers.py`:

| Prefix | Domain |
|--------|--------|
| `/admin_user` | Admin management |
| `/chat` | Sessions, messages, feedback |
| `/llm` | Main Q&A endpoint, STT |
| `/knowledge` | Knowledge base CRUD, file upload |
| `/faq` | FAQ management |
| `/inquiry` | Support tickets |
| `/model` | AI model config (singleton) |
| `/system` | System settings, quick categories |
| `/analytics` | Dashboard analytics |
| `/api_cost` | Usage cost tracking |
| `/notification` | Admin notifications |
| `/ws` | WebSocket endpoint |
| `/chat_history` | Chat session insights |
