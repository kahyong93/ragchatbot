"""Part 3: how RAGSystem handles content-related queries."""
from unittest.mock import MagicMock, patch

import pytest

from rag_system import RAGSystem


@pytest.fixture
def stub_config(tmp_path):
    cfg = MagicMock()
    cfg.CHUNK_SIZE, cfg.CHUNK_OVERLAP = 800, 100
    cfg.CHROMA_PATH, cfg.EMBEDDING_MODEL = str(tmp_path / "chroma"), "all-MiniLM-L6-v2"
    cfg.MAX_RESULTS, cfg.MAX_HISTORY = 5, 2
    cfg.OPENAI_API_KEY, cfg.OPENAI_MODEL = "test-key", "gpt-4o-mini"
    return cfg


@pytest.fixture
def rag(stub_config):
    """RAGSystem with vector store and generator mocked out."""
    with patch("rag_system.VectorStore"), patch("rag_system.AIGenerator"):
        yield RAGSystem(stub_config)


class TestOrchestration:
    def test_both_tools_are_registered(self, rag):
        names = {d["name"] for d in rag.tool_manager.get_tool_definitions()}
        assert names == {"search_course_content", "get_course_outline"}

    def test_query_passes_tools_to_the_generator(self, rag):
        rag.ai_generator.generate_response.return_value = "answer"
        rag.query("What is MCP?")
        kwargs = rag.ai_generator.generate_response.call_args.kwargs
        assert kwargs["tool_manager"] is rag.tool_manager
        assert {t["name"] for t in kwargs["tools"]} >= {"search_course_content"}

    def test_query_returns_answer_and_sources(self, rag):
        rag.ai_generator.generate_response.return_value = "MCP is a protocol."
        rag.search_tool.last_sources = [
            {"text": "MCP Course - Lesson 1", "link": "https://example.com/l1"}
        ]
        answer, sources = rag.query("What is MCP?")
        assert answer == "MCP is a protocol."
        assert sources == [
            {"text": "MCP Course - Lesson 1", "link": "https://example.com/l1"}
        ]

    def test_sources_are_reset_between_queries(self, rag):
        rag.ai_generator.generate_response.return_value = "answer"
        rag.search_tool.last_sources = [{"text": "A", "link": None}]
        rag.query("first")
        _, second_sources = rag.query("second")
        assert second_sources == []

    def test_history_is_threaded_through_the_session(self, rag):
        rag.ai_generator.generate_response.return_value = "answer"
        sid = rag.session_manager.create_session()
        rag.query("first question", session_id=sid)
        rag.query("second question", session_id=sid)
        history = rag.ai_generator.generate_response.call_args.kwargs[
            "conversation_history"
        ]
        assert history and "first question" in history


class TestRealContentQuery:
    """End-to-end against the real store/config, model call mocked.

    Asserts the tool actually produces content for the model - the step that
    breaks in production.
    """

    def test_content_query_yields_sources(self, real_rag):
        captured = {}

        def fake_generate(query, conversation_history=None, tools=None,
                          tool_manager=None):
            captured["result"] = tool_manager.execute_tool(
                "search_course_content", query="What is MCP?"
            )
            return "stubbed answer"

        real_rag.ai_generator.generate_response = fake_generate
        _, sources = real_rag.query("What is MCP?")

        assert not captured["result"].lower().startswith("search error"), (
            f"search tool errored: {captured['result']!r}"
        )
        assert sources, "content query produced no sources"


@pytest.fixture(scope="module")
def real_rag():
    from config import config
    system = RAGSystem(config)
    if not system.vector_store.get_existing_course_titles():
        pytest.skip("no courses indexed in chroma_db")
    return system
