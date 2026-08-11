# Changes — API Testing Infrastructure

Scope note: the requested work is backend test infrastructure. No frontend files
(`frontend/*.html|css|js`) were modified. This file records the changes as instructed.

## New files

### `backend/tests/__init__.py`
Makes the test directory a package.

### `backend/tests/conftest.py`
Shared fixtures:

- **Test data** — `sample_lessons`, `sample_course`, `sample_chunks`,
  `sample_query_response` (the `(answer, sources)` tuple `RAGSystem.query` returns),
  `sample_analytics`.
- **Mocks** — `mock_rag_system` (a `MagicMock` preconfigured with `query`,
  `get_course_analytics`, and `session_manager.create_session`), `mock_vector_store`.
- **App under test** — `create_test_app(rag_system)` rebuilds `/api/query`,
  `/api/courses`, and `/` with the same Pydantic models and handler logic as
  `backend/app.py`, but **without** `app.mount("/", StaticFiles(directory="../frontend"))`.
  That mount raises at import time whenever pytest runs from the repo root, which is
  why the routes are defined inline rather than imported. `/` returns a small JSON
  stand-in for the static frontend.
- **Client** — `test_app` and `client` (`TestClient` as a context manager, so
  lifespan events run).

`conftest.py` also prepends `backend/` to `sys.path` so the flat imports
(`config`, `models`, `rag_system`) resolve regardless of invocation directory.

### `backend/tests/test_api_endpoints.py`
15 tests, all marked `@pytest.mark.api`:

- **`/api/query`** — returns answer/sources/session_id; creates a session when none is
  supplied; reuses a supplied `session_id`; 422 on missing `query`; 422 on wrong type;
  empty query string accepted; empty sources serialize as `[]`; RAG exception → 500 with
  the message in `detail`; GET → 405.
- **`/api/courses`** — returns stats; handles an empty catalog; analytics exception → 500;
  POST → 405.
- **`/`** — reachable and returns JSON; unknown path → 404.

## Modified files

### `pyproject.toml`
Added a `[dependency-groups] dev` group (`pytest>=8.0`, `httpx>=0.27` — required by
`TestClient`) and `[tool.pytest.ini_options]`:

- `testpaths = ["backend/tests"]` and `pythonpath = ["backend"]` so `uv run pytest`
  works from the repo root.
- `addopts = ["-q", "--strict-markers", "--tb=short"]`.
- Registered markers: `api`, `unit`, `integration`.
- Warning filters for the noisy `DeprecationWarning`/`UserWarning` from chromadb and
  sentence-transformers.

## Running

```bash
uv sync            # installs the dev group
uv run pytest      # from the repo root
uv run pytest -m api
```

Result: **15 passed**.
