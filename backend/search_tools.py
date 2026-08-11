import json
from typing import Dict, Any, Optional, Protocol
from abc import ABC, abstractmethod
from vector_store import VectorStore, SearchResults


class Tool(ABC):
    """Abstract base class for all tools"""
    
    @abstractmethod
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return Anthropic tool definition for this tool"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool with given parameters"""
        pass


class CourseSearchTool(Tool):
    """Tool for searching course content with semantic course name matching"""
    
    def __init__(self, vector_store: VectorStore):
        self.store = vector_store
        self.last_sources = []  # Track sources from last search
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return Anthropic tool definition for this tool"""
        return {
            "name": "search_course_content",
            "description": "Search course materials with smart course name matching and lesson filtering",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "What to search for in the course content"
                    },
                    "course_name": {
                        "type": "string",
                        "description": "Course title (partial matches work, e.g. 'MCP', 'Introduction')"
                    },
                    "lesson_number": {
                        "type": "integer",
                        "description": "Specific lesson number to search within (e.g. 1, 2, 3)"
                    }
                },
                "required": ["query"]
            }
        }
    
    def execute(self, query: str, course_name: Optional[str] = None, lesson_number: Optional[int] = None) -> str:
        """
        Execute the search tool with given parameters.
        
        Args:
            query: What to search for
            course_name: Optional course filter
            lesson_number: Optional lesson filter
            
        Returns:
            Formatted search results or error message
        """
        
        # Use the vector store's unified search interface
        results = self.store.search(
            query=query,
            course_name=course_name,
            lesson_number=lesson_number
        )
        
        # Handle errors. Clear sources first: these early returns would
        # otherwise leave the previous query's sources in place, and the UI
        # would cite them for an answer they had no part in.
        if results.error:
            self.last_sources = []
            return results.error

        # Handle empty results
        if results.is_empty():
            self.last_sources = []
            filter_info = ""
            if course_name:
                filter_info += f" in course '{course_name}'"
            if lesson_number:
                filter_info += f" in lesson {lesson_number}"
            return f"No relevant content found{filter_info}."
        
        # Format and return results
        return self._format_results(results)
    
    def _format_results(self, results: SearchResults) -> str:
        """Format search results with course and lesson context"""
        formatted = []
        sources = []  # Track sources for the UI
        
        for doc, meta in zip(results.documents, results.metadata):
            course_title = meta.get('course_title', 'unknown')
            lesson_num = meta.get('lesson_number')
            
            # Build context header
            header = f"[{course_title}"
            if lesson_num is not None:
                header += f" - Lesson {lesson_num}"
            header += "]"
            
            # Track source for the UI, with a link when one is available
            source_text = course_title
            link = None
            if lesson_num is not None:
                source_text += f" - Lesson {lesson_num}"
                link = self.store.get_lesson_link(course_title, lesson_num)
            else:
                link = self.store.get_course_link(course_title)
            sources.append({"text": source_text, "link": link})
            
            formatted.append(f"{header}\n{doc}")
        
        # Store sources for retrieval
        self.last_sources = sources
        
        return "\n\n".join(formatted)

class CourseOutlineTool(Tool):
    """Tool for retrieving a course's outline from the catalog metadata"""

    def __init__(self, vector_store: VectorStore):
        self.store = vector_store
        self.last_sources = []  # Track sources from last lookup

    def get_tool_definition(self) -> Dict[str, Any]:
        """Return Anthropic tool definition for this tool"""
        return {
            "name": "get_course_outline",
            "description": "Get the full outline of a course: its title, link, and the number and title of every lesson. Use for questions about a course's structure, syllabus, or lesson list rather than its content",
            "input_schema": {
                "type": "object",
                "properties": {
                    "course_title": {
                        "type": "string",
                        "description": "Course title (partial matches work, e.g. 'MCP', 'Introduction')"
                    }
                },
                "required": ["course_title"]
            }
        }

    def execute(self, course_title: str) -> str:
        """
        Look up a course outline by title.

        Args:
            course_title: Course title, exact or partial

        Returns:
            Formatted outline or an error message
        """
        # Reuse the catalog's semantic matcher so a fuzzy title resolves the
        # same way it does for content search
        # Same reasoning as CourseSearchTool.execute: clear stale sources so a
        # failed lookup cannot cite the previous query's course.
        resolved_title = self.store._resolve_course_name(course_title)
        if not resolved_title:
            self.last_sources = []
            return f"No course found matching '{course_title}'."

        metadata = self._get_course_metadata(resolved_title)
        if metadata is None:
            self.last_sources = []
            return f"No outline found for course '{resolved_title}'."

        outline = self._format_outline(metadata)

        # The catalog lookup is nearest-neighbour with no distance floor, so an
        # unrecognized title still resolves to *some* course. Name the match when
        # it isn't an obvious one so a wrong guess is visible rather than silent.
        if course_title.strip().lower() not in resolved_title.lower():
            outline = (f"(Closest matching course for '{course_title}' — "
                       f"say so if this is not the course meant.)\n{outline}")

        return outline

    def _get_course_metadata(self, course_title: str) -> Optional[Dict[str, Any]]:
        """Fetch one course's catalog metadata, with lessons deserialized"""
        try:
            results = self.store.course_catalog.get(ids=[course_title])
        except Exception as e:
            print(f"Error getting course outline: {e}")
            return None

        if not results or not results.get('metadatas'):
            return None

        metadata = dict(results['metadatas'][0])
        lessons_json = metadata.get('lessons_json')
        metadata['lessons'] = json.loads(lessons_json) if lessons_json else []
        return metadata

    def _format_outline(self, metadata: Dict[str, Any]) -> str:
        """Format course title, link, and the full lesson list"""
        title = metadata.get('title', 'unknown')
        course_link = metadata.get('course_link')

        lines = [f"Course: {title}"]
        if course_link:
            lines.append(f"Course link: {course_link}")

        # Sort by lesson number so the outline reads in order regardless of
        # the order lessons were stored in
        lessons = sorted(
            metadata.get('lessons', []),
            key=lambda lesson: (lesson.get('lesson_number') is None,
                                lesson.get('lesson_number'))
        )

        if lessons:
            lines.append(f"Lessons ({len(lessons)}):")
            for lesson in lessons:
                number = lesson.get('lesson_number')
                lesson_title = lesson.get('lesson_title', 'untitled')
                label = f"Lesson {number}" if number is not None else "Lesson"
                lines.append(f"  {label}: {lesson_title}")
        else:
            lines.append("Lessons: none listed.")

        # Surface the course itself as the citation for the UI
        self.last_sources = [{"text": title, "link": course_link}]

        return "\n".join(lines)


class ToolManager:
    """Manages available tools for the AI"""
    
    def __init__(self):
        self.tools = {}
    
    def register_tool(self, tool: Tool):
        """Register any tool that implements the Tool interface"""
        tool_def = tool.get_tool_definition()
        tool_name = tool_def.get("name")
        if not tool_name:
            raise ValueError("Tool must have a 'name' in its definition")
        self.tools[tool_name] = tool

    
    def get_tool_definitions(self) -> list:
        """Get all tool definitions for Anthropic tool calling"""
        return [tool.get_tool_definition() for tool in self.tools.values()]
    
    def execute_tool(self, tool_name: str, **kwargs) -> str:
        """Execute a tool by name with given parameters"""
        if tool_name not in self.tools:
            return f"Tool '{tool_name}' not found"
        
        return self.tools[tool_name].execute(**kwargs)
    
    def get_last_sources(self) -> list:
        """Get sources from the last search operation"""
        # Check all tools for last_sources attribute
        for tool in self.tools.values():
            if hasattr(tool, 'last_sources') and tool.last_sources:
                return tool.last_sources
        return []

    def reset_sources(self):
        """Reset sources from all tools that track sources"""
        for tool in self.tools.values():
            if hasattr(tool, 'last_sources'):
                tool.last_sources = []