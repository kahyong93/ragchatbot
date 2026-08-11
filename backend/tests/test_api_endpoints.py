"""Request/response tests for the FastAPI endpoints.

The app under test comes from `conftest.create_test_app`, which reproduces the
routes in `backend/app.py` without the `../frontend` static mount.
"""

import pytest


@pytest.mark.api
class TestQueryEndpoint:
    def test_returns_answer_sources_and_session(self, client, sample_query_response):
        answer, sources = sample_query_response

        response = client.post("/api/query", json={"query": "What is MCP?"})

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == answer
        assert body["sources"] == sources
        assert body["session_id"] == "session_1"

    def test_creates_session_when_none_supplied(self, client, mock_rag_system):
        client.post("/api/query", json={"query": "What is MCP?"})

        mock_rag_system.session_manager.create_session.assert_called_once()
        mock_rag_system.query.assert_called_once_with("What is MCP?", "session_1")

    def test_reuses_supplied_session(self, client, mock_rag_system):
        response = client.post(
            "/api/query", json={"query": "Tell me more", "session_id": "session_42"}
        )

        assert response.status_code == 200
        assert response.json()["session_id"] == "session_42"
        mock_rag_system.session_manager.create_session.assert_not_called()
        mock_rag_system.query.assert_called_once_with("Tell me more", "session_42")

    def test_missing_query_field_is_422(self, client):
        assert client.post("/api/query", json={}).status_code == 422

    def test_wrong_query_type_is_422(self, client):
        assert client.post("/api/query", json={"query": 123}).status_code == 422

    def test_empty_query_string_is_accepted(self, client):
        """The API imposes no minimum length — it forwards to the RAG system."""
        assert client.post("/api/query", json={"query": ""}).status_code == 200

    def test_empty_sources_serialize_as_empty_list(self, client, mock_rag_system):
        mock_rag_system.query.return_value = ("No results found.", [])

        body = client.post("/api/query", json={"query": "unrelated"}).json()

        assert body["sources"] == []

    def test_rag_failure_becomes_500(self, client, mock_rag_system):
        mock_rag_system.query.side_effect = RuntimeError("vector store offline")

        response = client.post("/api/query", json={"query": "What is MCP?"})

        assert response.status_code == 500
        assert response.json()["detail"] == "vector store offline"

    def test_get_not_allowed(self, client):
        assert client.get("/api/query").status_code == 405


@pytest.mark.api
class TestCoursesEndpoint:
    def test_returns_course_stats(self, client, sample_analytics):
        response = client.get("/api/courses")

        assert response.status_code == 200
        assert response.json() == sample_analytics

    def test_empty_catalog(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.return_value = {
            "total_courses": 0,
            "course_titles": [],
        }

        body = client.get("/api/courses").json()

        assert body == {"total_courses": 0, "course_titles": []}

    def test_analytics_failure_becomes_500(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.side_effect = RuntimeError("chroma down")

        response = client.get("/api/courses")

        assert response.status_code == 500
        assert response.json()["detail"] == "chroma down"

    def test_post_not_allowed(self, client):
        assert client.post("/api/courses", json={}).status_code == 405


@pytest.mark.api
class TestRootEndpoint:
    def test_root_is_reachable(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert "message" in response.json()

    def test_unknown_path_is_404(self, client):
        assert client.get("/api/does-not-exist").status_code == 404
