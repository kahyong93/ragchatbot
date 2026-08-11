"""Part 2: does AIGenerator correctly call CourseSearchTool?

The OpenAI client is mocked throughout - these assert on wiring
(schema translation, dispatch, tool_call_id pairing), not model quality.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from ai_generator import AIGenerator
from search_tools import CourseSearchTool, ToolManager
from conftest import make_completion, make_openai_message, make_tool_call


@pytest.fixture
def tool_manager(mock_store):
    manager = ToolManager()
    manager.register_tool(CourseSearchTool(mock_store))
    return manager


@pytest.fixture
def generator():
    with patch("ai_generator.OpenAI"):
        yield AIGenerator(api_key="test-key", model="gpt-4o-mini")


class TestToolSchemaTranslation:
    def test_anthropic_schema_becomes_openai_function(self, tool_manager):
        converted = AIGenerator._to_openai_tools(tool_manager.get_tool_definitions())
        search = next(t for t in converted
                      if t["function"]["name"] == "search_course_content")
        assert search["type"] == "function"
        assert search["function"]["parameters"]["required"] == ["query"]
        assert "query" in search["function"]["parameters"]["properties"]

    def test_tools_are_offered_to_the_model(self, generator, tool_manager):
        generator.client.chat.completions.create.return_value = make_completion(
            make_openai_message(content="hi")
        )
        generator.generate_response(
            query="What is MCP?",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        params = generator.client.chat.completions.create.call_args.kwargs
        assert params["tool_choice"] == "auto"
        assert {t["function"]["name"] for t in params["tools"]} >= {
            "search_course_content"
        }


class TestToolDispatch:
    def test_tool_call_reaches_the_search_tool(self, generator, tool_manager):
        tc = make_tool_call("search_course_content",
                            json.dumps({"query": "What is MCP?"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="MCP is a protocol.")),
        ]
        manager_spy = MagicMock(wraps=tool_manager)

        answer = generator.generate_response(
            query="What is MCP?",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=manager_spy,
        )

        manager_spy.execute_tool.assert_called_once_with(
            "search_course_content", query="What is MCP?"
        )
        assert answer == "MCP is a protocol."
        # Round 1 called the tool, round 2 answered in prose - no extra call
        assert generator.client.chat.completions.create.call_count == 2

    def test_arguments_are_forwarded(self, generator, tool_manager, mock_store):
        tc = make_tool_call(
            "search_course_content",
            json.dumps({"query": "architecture", "course_name": "MCP",
                        "lesson_number": 2}),
        )
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="done")),
        ]
        generator.generate_response(
            query="lesson 2?",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        mock_store.search.assert_called_once_with(
            query="architecture", course_name="MCP", lesson_number=2
        )

    def test_tool_result_is_sent_back_keyed_by_call_id(self, generator, tool_manager):
        tc = make_tool_call("search_course_content",
                            json.dumps({"query": "q"}), call_id="call_abc")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="final")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        follow_up = generator.client.chat.completions.create.call_args_list[1]
        tool_msgs = [m for m in follow_up.kwargs["messages"]
                     if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_abc"
        assert "MCP is a protocol for context." in tool_msgs[0]["content"]

    def test_second_round_still_offers_tools(self, generator, tool_manager):
        """The model must be able to search again after seeing round-1 results."""
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="final")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        second_call = generator.client.chat.completions.create.call_args_list[1]
        assert "tools" in second_call.kwargs
        assert second_call.kwargs["tool_choice"] == "auto"

    def test_no_tool_call_returns_direct_answer(self, generator, tool_manager):
        generator.client.chat.completions.create.return_value = make_completion(
            make_openai_message(content="General knowledge answer.")
        )
        answer = generator.generate_response(
            query="What is 2+2?",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        assert answer == "General knowledge answer."
        # Guards the return-vs-break bug: no wasted synthesis call
        assert generator.client.chat.completions.create.call_count == 1

    def test_tool_error_string_is_passed_to_the_model(self, generator,
                                                     tool_manager, mock_store):
        """When search fails, the model still gets the error as tool output.

        This is how a MAX_RESULTS=0 failure surfaces: no exception, just an
        error string the model then paraphrases or ignores.
        """
        from vector_store import SearchResults
        mock_store.search.return_value = SearchResults.empty(
            "Search error: Number of requested results 0, cannot be negative, or zero."
        )
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="I could not find that.")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        follow_up = generator.client.chat.completions.create.call_args_list[1]
        tool_msg = next(m for m in follow_up.kwargs["messages"]
                        if m.get("role") == "tool")
        assert "Search error" in tool_msg["content"]


@pytest.fixture
def both_tools(mock_store):
    """Manager with both tools registered, for chaining tests."""
    from search_tools import CourseOutlineTool
    mock_store._resolve_course_name.return_value = "MCP Course"
    mock_store.course_catalog.get.return_value = {
        "metadatas": [{
            "title": "MCP Course",
            "course_link": "https://example.com/course",
            "lessons_json": json.dumps([
                {"lesson_number": 4, "lesson_title": "Creating An MCP Server",
                 "lesson_link": "https://example.com/l4"},
            ]),
        }]
    }
    manager = ToolManager()
    manager.register_tool(CourseSearchTool(mock_store))
    manager.register_tool(CourseOutlineTool(mock_store))
    return manager


class TestSequentialRounds:
    """The feature: two tool rounds with reasoning in between."""

    def test_two_round_chain_executes_both_tools_in_order(self, generator, both_tools):
        outline_call = make_tool_call("get_course_outline",
                                      json.dumps({"course_title": "MCP"}),
                                      call_id="c1")
        search_call = make_tool_call("search_course_content",
                                     json.dumps({"query": "Creating An MCP Server"}),
                                     call_id="c2")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[outline_call])),
            make_completion(make_openai_message(tool_calls=[search_call])),
            make_completion(make_openai_message(content="Course Y covers it.")),
        ]
        spy = MagicMock(wraps=both_tools)

        answer = generator.generate_response(
            query="Find a course on the same topic as lesson 4 of MCP",
            tools=both_tools.get_tool_definitions(),
            tool_manager=spy,
        )

        assert [c.args[0] for c in spy.execute_tool.call_args_list] == [
            "get_course_outline", "search_course_content"
        ]
        assert answer == "Course Y covers it."
        assert generator.client.chat.completions.create.call_count == 3

    def test_round_two_sees_round_one_tool_result(self, generator, both_tools):
        outline_call = make_tool_call("get_course_outline",
                                      json.dumps({"course_title": "MCP"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[outline_call])),
            make_completion(make_openai_message(content="done")),
        ]
        generator.generate_response(
            query="q",
            tools=both_tools.get_tool_definitions(),
            tool_manager=both_tools,
        )
        second_messages = (
            generator.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        )
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "Creating An MCP Server" in tool_msgs[0]["content"]
        # The assistant's tool-call message must precede its reply
        roles = [m.get("role") for m in second_messages]
        assert roles.index("assistant") < roles.index("tool")

    def test_terminal_call_omits_tools(self, generator, tool_manager):
        """After the budget is spent, tools are withheld so prose is forced."""
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="answer")),
        ]
        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        calls = generator.client.chat.completions.create.call_args_list
        assert generator.client.chat.completions.create.call_count == 3
        assert "tools" not in calls[2].kwargs
        assert answer == "answer"

    def test_stops_at_two_rounds_even_if_model_keeps_calling(self, generator,
                                                            tool_manager):
        """Anti-runaway: a model that always wants tools still terminates."""
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))

        def always_tool_calls(**kwargs):
            if "tools" in kwargs:
                return make_completion(make_openai_message(tool_calls=[tc]))
            return make_completion(make_openai_message(content="forced answer"))

        generator.client.chat.completions.create.side_effect = always_tool_calls
        spy = MagicMock(wraps=tool_manager)

        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=spy,
        )
        assert generator.client.chat.completions.create.call_count == 3
        assert spy.execute_tool.call_count == 2
        assert answer == "forced answer"

    def test_max_tool_rounds_override_is_respected(self, generator, tool_manager):
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="answer")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
            max_tool_rounds=1,
        )
        calls = generator.client.chat.completions.create.call_args_list
        assert generator.client.chat.completions.create.call_count == 2
        assert "tools" not in calls[1].kwargs

    def test_parallel_tool_calls_each_get_a_reply(self, generator, tool_manager):
        tc1 = make_tool_call("search_course_content",
                             json.dumps({"query": "a"}), call_id="c1")
        tc2 = make_tool_call("search_course_content",
                             json.dumps({"query": "b"}), call_id="c2")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc1, tc2])),
            make_completion(make_openai_message(content="answer")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        second_messages = (
            generator.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        )
        ids = [m["tool_call_id"] for m in second_messages if m.get("role") == "tool"]
        assert ids == ["c1", "c2"]


class TestTerminationAndFallback:
    """No path may return an empty answer to the user."""

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_final_content_returns_fallback(self, generator, tool_manager, blank):
        generator.client.chat.completions.create.return_value = make_completion(
            make_openai_message(content=blank)
        )
        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        assert answer == AIGenerator.FALLBACK_ANSWER
        assert answer.strip() != ""

    def test_blank_answer_without_tools_returns_fallback(self, generator):
        generator.client.chat.completions.create.return_value = make_completion(
            make_openai_message(content=None)
        )
        assert generator.generate_response(query="q") == AIGenerator.FALLBACK_ANSWER

    def test_prose_alongside_tool_calls_is_not_the_final_answer(self, generator,
                                                               tool_manager):
        """A preamble like 'Let me check' must not be returned as the answer."""
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(content="Let me check.",
                                                tool_calls=[tc])),
            make_completion(make_openai_message(content="The answer.")),
        ]
        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        assert answer == "The answer."


class TestErrorSemantics:
    """Strings are data; exceptions are faults. Only faults stop the chain."""

    def test_raising_tool_aborts_chain_but_still_answers(self, generator,
                                                        tool_manager, mock_store):
        mock_store.search.side_effect = RuntimeError("chroma down")
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="I could not retrieve that.")),
        ]
        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        calls = generator.client.chat.completions.create.call_args_list
        # Round 2 skipped: round 1 + terminal synthesis only
        assert generator.client.chat.completions.create.call_count == 2
        assert "tools" not in calls[1].kwargs
        tool_msg = next(m for m in calls[1].kwargs["messages"]
                        if m.get("role") == "tool")
        assert "failed" in tool_msg["content"]
        assert answer == "I could not retrieve that."

    def test_raising_tool_still_replies_to_every_call_id(self, generator,
                                                        tool_manager, mock_store):
        """An unanswered tool_call_id would make the next request malformed."""
        mock_store.search.side_effect = RuntimeError("boom")
        tc1 = make_tool_call("search_course_content",
                             json.dumps({"query": "a"}), call_id="c1")
        tc2 = make_tool_call("search_course_content",
                             json.dumps({"query": "b"}), call_id="c2")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc1, tc2])),
            make_completion(make_openai_message(content="answer")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        final_messages = (
            generator.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        )
        ids = [m["tool_call_id"] for m in final_messages if m.get("role") == "tool"]
        assert ids == ["c1", "c2"]

    def test_error_string_does_not_abort_the_chain(self, generator, tool_manager,
                                                   mock_store):
        from vector_store import SearchResults
        mock_store.search.return_value = SearchResults.empty("Search error: nope")
        tc = make_tool_call("search_course_content", json.dumps({"query": "q"}))
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(tool_calls=[tc])),
            make_completion(make_openai_message(content="answer")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        # The model still got its second round despite the error string
        assert generator.client.chat.completions.create.call_count == 3

    def test_unknown_tool_name_does_not_abort_the_chain(self, generator, tool_manager):
        bad = make_tool_call("nonexistent_tool", json.dumps({"x": 1}), call_id="c1")
        good = make_tool_call("search_course_content",
                              json.dumps({"query": "q"}), call_id="c2")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[bad])),
            make_completion(make_openai_message(tool_calls=[good])),
            make_completion(make_openai_message(content="answer")),
        ]
        generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        assert generator.client.chat.completions.create.call_count == 3
        second_messages = (
            generator.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        )
        tool_msg = next(m for m in second_messages if m.get("role") == "tool")
        assert "not found" in tool_msg["content"]

    def test_malformed_arguments_do_not_crash_or_abort(self, generator, tool_manager):
        bad = make_tool_call("search_course_content", "{not json", call_id="c1")
        generator.client.chat.completions.create.side_effect = [
            make_completion(make_openai_message(tool_calls=[bad])),
            make_completion(make_openai_message(content="answer")),
        ]
        answer = generator.generate_response(
            query="q",
            tools=tool_manager.get_tool_definitions(),
            tool_manager=tool_manager,
        )
        second_messages = (
            generator.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        )
        tool_msg = next(m for m in second_messages if m.get("role") == "tool")
        assert "Invalid tool arguments" in tool_msg["content"]
        assert answer == "answer"


class TestSystemPrompt:
    def test_prompt_names_the_search_tool(self):
        assert "search_course_content" in AIGenerator.SYSTEM_PROMPT

    def test_prompt_permits_two_sequential_rounds(self):
        assert "One tool call per query maximum" not in AIGenerator.SYSTEM_PROMPT
        assert "2 sequential rounds" in AIGenerator.SYSTEM_PROMPT

    def test_history_is_injected_into_system_message(self, generator):
        generator.client.chat.completions.create.return_value = make_completion(
            make_openai_message(content="ok")
        )
        generator.generate_response(query="q", conversation_history="User: hi")
        messages = generator.client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "User: hi" in messages[0]["content"]
