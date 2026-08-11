"""Shared fixtures for the backend test suite.

Tests live in backend/tests but the modules under test are flat imports
(`from search_tools import ...`), matching how the app is launched from
`backend/`. Put backend/ on sys.path so both work.

The real `backend/app.py` mounts `../frontend` as static files at import time,
which fails whenever the tests are not run from `backend/`. Tests therefore use
`test_app` below, which rebuilds the same API surface without the static mount.
"""

import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

# Make `backend/` importable as a flat package root (config, rag_system, ...)
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from models import Course, CourseChunk, Lesson  # noqa: E402
from vector_store import SearchResults  # noqa: E402


# --------------------------------------------------------------------------
# Test data
# --------------------------------------------------------------------------


@pytest.fixture
def sample_lessons():
    return [
        Lesson(lesson_number=0, title="Introduction", lesson_link="http://example.com/l0"),
        Lesson(lesson_number=1, title="Deep Dive", lesson_link="http://example.com/l1"),
    ]


@pytest.fixture
def sample_course(sample_lessons):
    return Course(
        title="MCP: Build Rich-Context AI Apps",
        course_link="http://example.com/course",
        instructor="Test Instructor",
        lessons=sample_lessons,
    )


@pytest.fixture
def sample_chunks(sample_course):
    return [
        CourseChunk(
            content="Course MCP: Build Rich-Context AI Apps Lesson 0 content: MCP is a protocol.",
            course_title=sample_course.title,
            lesson_number=0,
            chunk_index=0,
        ),
        CourseChunk(
            content="Lesson 1 content: Servers expose tools to the model.",
            course_title=sample_course.title,
            lesson_number=1,
            chunk_index=1,
        ),
    ]


@pytest.fixture
def sample_results():
    """Two content chunks as VectorStore.search would return them."""
    return SearchResults(
        documents=["MCP is a protocol for context.", "Servers expose tools."],
        metadata=[
            {"course_title": "MCP Course", "lesson_number": 1, "chunk_index": 0},
            {"course_title": "MCP Course", "lesson_number": 2, "chunk_index": 1},
        ],
        distances=[0.11, 0.22],
    )


@pytest.fixture
def sample_query_response():
    """The (answer, sources) tuple shape returned by RAGSystem.query."""
    return (
        "MCP is a protocol for connecting models to tools.",
        ["MCP: Build Rich-Context AI Apps - Lesson 0"],
    )


@pytest.fixture
def sample_analytics(sample_course):
    return {"total_courses": 1, "course_titles": [sample_course.title]}


# --------------------------------------------------------------------------
# Mocks
# --------------------------------------------------------------------------


@pytest.fixture
def mock_store(sample_results):
    """A VectorStore stand-in that returns results and resolves links."""
    store = MagicMock()
    store.search.return_value = sample_results
    store.get_lesson_link.return_value = "https://example.com/lesson"
    store.get_course_link.return_value = "https://example.com/course"
    return store


@pytest.fixture
def mock_rag_system(sample_query_response, sample_analytics):
    """A stand-in for RAGSystem with the surface the API endpoints use."""
    rag = MagicMock()
    rag.query.return_value = sample_query_response
    rag.get_course_analytics.return_value = sample_analytics
    rag.session_manager.create_session.return_value = "session_1"
    return rag


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    store.search.return_value = MagicMock(documents=[], metadata=[], error=None)
    return store


def make_openai_message(content=None, tool_calls=None):
    """Build a stand-in for an OpenAI ChatCompletion message.

    The generator calls `.model_dump(exclude_none=True)` on the assistant
    message to append it to the transcript, so the mock must support that. The
    dump mirrors a real one: it carries `tool_calls` through (as id/function
    dicts) and omits keys whose value is None, so a round-2 request contains the
    same assistant message the real API would have produced.
    """
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls

    dumped = {"role": "assistant"}
    if content is not None:
        dumped["content"] = content
    if tool_calls is not None:
        dumped["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]
    msg.model_dump.return_value = dumped
    return msg


def make_tool_call(name, arguments_json, call_id="call_1"):
    """Build a stand-in for a single OpenAI tool_call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments_json
    return tc


def make_completion(message):
    """Wrap a message in a ChatCompletion-shaped response."""
    completion = MagicMock()
    completion.choices = [MagicMock(message=message)]
    return completion


# --------------------------------------------------------------------------
# API app under test (no static mount)
# --------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[str]
    session_id: str


class CourseStats(BaseModel):
    total_courses: int
    course_titles: List[str]


def create_test_app(rag_system):
    """Mirror of backend/app.py's API routes, minus the static file mount.

    Keep the handler bodies in sync with `app.py` — they exist separately only
    because `app.mount("/", StaticFiles(directory="../frontend"))` raises at
    import time when the CWD is not `backend/`.
    """
    app = FastAPI(title="Course Materials RAG System (test)")

    @app.post("/api/query", response_model=QueryResponse)
    async def query_documents(request: QueryRequest):
        try:
            session_id = request.session_id
            if not session_id:
                session_id = rag_system.session_manager.create_session()
            answer, sources = rag_system.query(request.query, session_id)
            return QueryResponse(answer=answer, sources=sources, session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/courses", response_model=CourseStats)
    async def get_course_stats():
        try:
            analytics = rag_system.get_course_analytics()
            return CourseStats(
                total_courses=analytics["total_courses"],
                course_titles=analytics["course_titles"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/")
    async def root():
        """Stands in for the static frontend served at / in production."""
        return {"message": "Course Materials RAG System"}

    return app


@pytest.fixture
def test_app(mock_rag_system):
    return create_test_app(mock_rag_system)


@pytest.fixture
def client(test_app):
    with TestClient(test_app) as c:
        yield c
