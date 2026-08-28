"""Content Agent — ideas, drafts, and repurposing across formats."""

from ray.agents.registry import get_agent_spec
from ray.agents.tool_agent import ToolUsingAgent
from ray.tools.types import ToolResult


class ContentAgent(ToolUsingAgent):
    spec = get_agent_spec("content")
    prompt_name = "content"

    def _render_tool_result(self, result: ToolResult) -> str:
        if result.status == "executed":
            return f"Tool result ({result.tool}): {result.data}"
        return f"Tool result ({result.tool}): {result.for_model()}"
