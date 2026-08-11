import json
from openai import OpenAI
from typing import List, Optional, Dict, Any

class AIGenerator:
    """Handles interactions with OpenAI's Chat Completions API for generating responses"""
    
    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to tools for course information.

Tool Usage:
- **search_course_content**: Use **only** for questions about specific course content or detailed educational materials
- **get_course_outline**: Use for questions about a course's structure, syllabus, or list of lessons
- **You may use tools in up to 2 sequential rounds.** After each round you see the
  results and may call another tool. Use the second round only when the first
  round's results tell you something you needed in order to search well — for
  example, getting a course outline to learn a lesson's exact title, then
  searching that lesson's content. Most questions need only one round.
- **Do not call both tools at once speculatively.** Call one tool, read its
  result, then decide whether a second call is genuinely needed. Calling tools in
  parallel wastes the round and gives you no chance to use the first result.
- After 2 rounds you must answer from what you have. If the results are
  insufficient, say so plainly rather than asking for another search.
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results, state this clearly without offering alternatives

Outline Responses:
- When answering an outline question, report all of the following from the tool result:
 - the course title
 - the course link
 - every lesson, each with its lesson number and lesson title
- Present the lessons in order and do not omit or summarize away any of them

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without searching
- **Course-specific questions**: Search first, then answer
- **Course outline questions**: Retrieve the outline first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly, except for outline questions, where the complete lesson list always takes precedence over brevity
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""
    
    # A "round" is one API call that offers tools, plus execution of any tools it
    # returns. The terminal synthesis call offers no tools and executes nothing,
    # so it is not a round: worst case is MAX_TOOL_ROUNDS + 1 = 3 API calls.
    MAX_TOOL_ROUNDS = 2

    FALLBACK_ANSWER = ("I wasn't able to produce an answer for that. "
                       "Please try rephrasing your question.")

    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 800
        }

    @staticmethod
    def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Anthropic-style tool definitions into OpenAI function tools.

        Tools declare themselves in Anthropic shape (see search_tools.py); the
        translation lives here so tool authors don't need to know the provider.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"]
                }
            }
            for tool in tools
        ]

    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None,
                         max_tool_rounds: Optional[int] = None) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Runs up to `max_tool_rounds` sequential tool rounds. Each round is its own
        API request that offers tools, so the model can read the previous round's
        results before deciding whether to call another tool. Stops when the model
        replies without tool calls, when a tool raises, or when the round budget
        is spent.

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools
            max_tool_rounds: Override the default round budget

        Returns:
            Generated response as string (never empty)
        """
        max_rounds = self.MAX_TOOL_ROUNDS if max_tool_rounds is None else max_tool_rounds

        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query}
        ]

        # Only advertise tools we can actually execute
        openai_tools = self._to_openai_tools(tools) if tools else None
        tools_available = bool(openai_tools and tool_manager)

        if not tools_available:
            response = self.client.chat.completions.create(
                **self.base_params, messages=messages
            )
            return self._text_or_fallback(response.choices[0].message)

        for _ in range(max_rounds):
            api_params = {
                **self.base_params,
                "messages": messages,
                "tools": openai_tools,
                "tool_choice": "auto",
            }
            message = self.client.chat.completions.create(**api_params).choices[0].message

            # The model answered in prose - return it directly. This must be a
            # return, not a break: breaking would discard this answer and spend
            # another API call re-asking for it.
            if not message.tool_calls:
                return self._text_or_fallback(message)

            messages.append(message.model_dump(exclude_none=True))

            # A raising tool means the environment is broken, not that the model
            # made a recoverable mistake, so stop chaining and go synthesize.
            if not self._append_tool_results(messages, message.tool_calls, tool_manager):
                break

        # Budget spent (or a tool failed) while the last message still wanted
        # tools. Omitting `tools` here makes further tool_calls impossible, so
        # this call always yields prose.
        return self._final_answer(messages)

    def _append_tool_results(self, messages: List[Dict[str, Any]], tool_calls,
                             tool_manager) -> bool:
        """
        Execute each tool call and append its reply to `messages`.

        Every tool_call_id gets exactly one reply even when it fails - an
        assistant tool-call message with an unanswered id is malformed and the
        API rejects the next request.

        Returns:
            False if any tool raised (an infrastructure fault), True otherwise.
            Error *strings* returned by a tool are ordinary data, not failures:
            "No course found matching X" is exactly the feedback that lets the
            next round retry with a better argument.
        """
        healthy = True

        for tool_call in tool_calls:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError as e:
                # Malformed arguments are a model mistake, recoverable next round
                content = f"Invalid tool arguments: {e}"
            else:
                try:
                    content = tool_manager.execute_tool(
                        tool_call.function.name,
                        **arguments
                    )
                except Exception as e:
                    content = f"Tool '{tool_call.function.name}' failed: {e}"
                    healthy = False

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                # Message content must be a string; execute_tool is typed to
                # return one but nothing enforces it
                "content": content if isinstance(content, str) else str(content)
            })

        return healthy

    def _final_answer(self, messages: List[Dict[str, Any]]) -> str:
        """Make a terminal synthesis call with no tools offered."""
        response = self.client.chat.completions.create(
            **self.base_params, messages=messages
        )
        return self._text_or_fallback(response.choices[0].message)

    @classmethod
    def _text_or_fallback(cls, message) -> str:
        """Return the message text, substituting a fallback when it is blank.

        Every exit from generate_response goes through here, so a blank model
        response can never reach the user as an empty answer.
        """
        text = (message.content or "").strip()
        return text or cls.FALLBACK_ANSWER