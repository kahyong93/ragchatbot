# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with `uv` (Python >= 3.13).

**Always use `uv` — never `pip` directly, and never invoke bare `python`/`uvicorn`.** Every Python process goes through `uv run`; dependency changes go through `uv add` / `uv sync` so `pyproject.toml` and `uv.lock` stay in sync.

```bash
uv sync                                          # install deps
uv add <package>                                 # add a dependency (not pip install)
./run.sh                                         # start server (Git Bash on Windows)
cd backend && uv run uvicorn app:app --reload --port 8000   # equivalent manual start
uv run python -c "..."                           # any ad-hoc Python
```

App serves the frontend at `http://localhost:8000` and OpenAPI docs at `/docs`.

Requires a `.env` in the repo root with `ANTHROPIC_API_KEY=...` (see `.env.example`).

There is no test suite, linter, or formatter configured. `main.py` at the root is an unused stub — the real entrypoint is `backend/app.py`.

## Architecture

A tool-calling RAG system: Claude decides *whether* to search rather than the backend always retrieving. `RAGSystem.query()` never touches the vector store directly — it passes tool definitions to `AIGenerator`, and retrieval only happens if Claude emits a `tool_use` block.

Request flow (`backend/`):

```
app.py (FastAPI)  →  rag_system.py (orchestrator)
                        ├─ ai_generator.py    → Anthropic Messages API + tool loop
                        │     └─ search_tools.py (ToolManager → CourseSearchTool)
                        │            └─ vector_store.py (ChromaDB)
                        └─ session_manager.py (in-memory history)
```

Key design points:

- **Two ChromaDB collections** (`vector_store.py`): `course_catalog` holds one document per course (title as both ID and embedded text, lessons serialized into `lessons_json` metadata); `course_content` holds the chunks. A search with a `course_name` filter first does a *semantic* lookup against `course_catalog` to resolve a fuzzy name ("MCP") to an exact title, then uses that title as a metadata filter on `course_content`. Course titles are therefore primary keys — two courses with the same title collide.
- **Single tool round-trip** (`ai_generator.py::_handle_tool_execution`): after tool results are appended, the follow-up API call deliberately omits `tools`, so Claude cannot search twice. The system prompt also states "One search per query maximum". Enabling multi-step search means changing both.
- **Sources are side-channel state**: `CourseSearchTool.last_sources` is set during `execute()`, read via `ToolManager.get_last_sources()` after generation completes, then reset. Not returned through the tool result string.
- **Adding a new tool**: subclass `Tool` in `search_tools.py`, register it on `RAGSystem.tool_manager`. `ToolManager` dispatches by the `name` in the tool definition.
- **Session history** is in-process only (`session_manager.py`), keyed by `session_N`, trimmed to `MAX_HISTORY` exchanges, and injected into the system prompt as plain text — not as message turns.

## Document ingestion

`docs/*.txt` are loaded on FastAPI startup (`app.py::startup_event`, path `../docs` relative to `backend/`). Ingestion is **skip-if-exists** by course title, so editing a doc or changing chunking parameters will *not* re-index it — delete `./chroma_db` (relative to `backend/`) or call `add_course_folder(..., clear_existing=True)` to rebuild.

`document_processor.py` expects this exact file structure:

```
Course Title: [title]
Course Link: [url]
Course Instructor: [name]

Lesson 0: [lesson title]
Lesson Link: [url]
[content...]
Lesson 1: ...
```

Chunking is sentence-based with character-count overlap (`CHUNK_SIZE`/`CHUNK_OVERLAP` in `config.py`). Note an existing inconsistency: chunks from the *last* lesson in a file get prefixed `Course {title} Lesson {n} content:` on every chunk, while earlier lessons prefix only the first chunk with `Lesson {n} content:`.

## Configuration

All tunables live in `backend/config.py` as a single `Config` dataclass instance (`config`), including `ANTHROPIC_MODEL`, `EMBEDDING_MODEL` (sentence-transformers, runs locally), chunking sizes, `MAX_RESULTS`, and `CHROMA_PATH`. `CHROMA_PATH` is relative, so the DB lands wherever the process was started — always launch from `backend/`.

## Frontend

`frontend/` is plain HTML/CSS/JS with no build step, served as static files by FastAPI (`DevStaticFiles` sends no-cache headers). It talks to `/api/query` and `/api/courses`; the session ID returned by the first query must be echoed back on subsequent ones to retain history.
