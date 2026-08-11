"""Shared fixtures for the backend test suite.

Tests live in backend/tests but the modules under test are flat imports
(`from search_tools import ...`), matching how the app is launched from
`backend/`. Put backend/ on sys.path so both work.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from vector_store import SearchResults  # noqa: E402


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
def mock_store(sample_results):
    """A VectorStore stand-in that returns results and resolves links."""
    store = MagicMock()
    store.search.return_value = sample_results
    store.get_lesson_link.return_value = "https://example.com/lesson"
    store.get_course_link.return_value = "https://example.com/course"
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
