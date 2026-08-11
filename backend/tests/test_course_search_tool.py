"""Part 1: outputs of CourseSearchTool.execute."""
import pytest

from search_tools import CourseSearchTool
from vector_store import SearchResults


class TestExecuteOutput:
    """execute() with a stubbed store - pure formatting/plumbing behaviour."""

    def test_returns_formatted_documents(self, mock_store):
        out = CourseSearchTool(mock_store).execute(query="What is MCP?")
        assert "MCP is a protocol for context." in out
        assert "Servers expose tools." in out

    def test_includes_course_and_lesson_header(self, mock_store):
        out = CourseSearchTool(mock_store).execute(query="What is MCP?")
        assert "[MCP Course - Lesson 1]" in out
        assert "[MCP Course - Lesson 2]" in out

    def test_passes_filters_through_to_store(self, mock_store):
        CourseSearchTool(mock_store).execute(
            query="architecture", course_name="MCP", lesson_number=2
        )
        mock_store.search.assert_called_once_with(
            query="architecture", course_name="MCP", lesson_number=2
        )

    def test_populates_last_sources(self, mock_store):
        tool = CourseSearchTool(mock_store)
        tool.execute(query="What is MCP?")
        assert tool.last_sources == [
            {"text": "MCP Course - Lesson 1", "link": "https://example.com/lesson"},
            {"text": "MCP Course - Lesson 2", "link": "https://example.com/lesson"},
        ]

    def test_store_error_is_returned_verbatim(self, mock_store):
        mock_store.search.return_value = SearchResults.empty("Search error: boom")
        out = CourseSearchTool(mock_store).execute(query="anything")
        assert out == "Search error: boom"

    def test_empty_results_message_names_filters(self, mock_store):
        mock_store.search.return_value = SearchResults([], [], [])
        out = CourseSearchTool(mock_store).execute(
            query="x", course_name="MCP", lesson_number=3
        )
        assert "No relevant content found" in out
        assert "MCP" in out and "lesson 3" in out

    def test_empty_results_do_not_leave_stale_sources(self, mock_store):
        """A hit followed by a miss must not report the previous hit's sources."""
        tool = CourseSearchTool(mock_store)
        tool.execute(query="hit")
        mock_store.search.return_value = SearchResults([], [], [])
        tool.execute(query="miss")
        assert tool.last_sources == []


class TestExecuteAgainstRealStore:
    """execute() against the real ChromaDB + real config.

    These are the tests that catch the reported production failure; the
    stubbed tests above pass regardless of configuration.
    """

    def test_search_returns_content_not_an_error(self, real_tool):
        out = real_tool.execute(query="What is MCP?")
        assert not out.lower().startswith("search error"), (
            f"CourseSearchTool.execute returned an error string: {out!r}"
        )

    def test_search_finds_indexed_content(self, real_tool):
        out = real_tool.execute(query="What is MCP?")
        assert "No relevant content found" not in out
        assert len(out.strip()) > 0

    def test_max_results_is_usable(self, real_config):
        """MAX_RESULTS feeds ChromaDB's n_results, which rejects 0."""
        assert real_config.MAX_RESULTS > 0, (
            f"MAX_RESULTS is {real_config.MAX_RESULTS}; ChromaDB rejects "
            "n_results<=0, so every content search fails."
        )


@pytest.fixture(scope="module")
def real_config():
    from config import config
    return config


@pytest.fixture(scope="module")
def real_tool(real_config):
    from vector_store import VectorStore
    store = VectorStore(
        real_config.CHROMA_PATH,
        real_config.EMBEDDING_MODEL,
        real_config.MAX_RESULTS,
    )
    if not store.get_existing_course_titles():
        pytest.skip("no courses indexed in chroma_db")
    return CourseSearchTool(store)
