"""Shared fixtures for the backend test suite.

The real `backend/app.py` mounts `../frontend` as static files at import time,
which fails whenever the tests are not run from `backend/`. Tests therefore use
`test_app` below, which rebuilds the same API surface without the static mount.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make `backend/` importable as a flat package root (config, rag_system, ...)
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typing import List, Optional

from models import Course, CourseChunk, Lesson


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
