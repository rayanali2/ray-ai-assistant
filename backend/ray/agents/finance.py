"""Finance Agent — local budget, subscriptions, savings goals, and spending summaries.

All financial data stays in the user's own database. The agent never calls an external
financial API or payment service.
"""

from ray.agents.registry import get_agent_spec
from ray.agents.tool_agent import ToolUsingAgent
from ray.tools.types import ToolResult


class FinanceAgent(ToolUsingAgent):
    spec = get_agent_spec("finance")
    prompt_name = "finance"

    def _render_tool_result(self, result: ToolResult) -> str:
        if result.status == "executed":
            return f"Tool result ({result.tool}): {result.data}"
        return f"Tool result ({result.tool}): {result.for_model()}"
