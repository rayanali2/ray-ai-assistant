"""Executive routing: which specialist should answer the user's request.

Routing is one LLM call with one ``delegate`` function per enabled specialist.
Single-agent routing is the default; the Executive itself answers when no delegate
is called, and fan-out happens only when the model explicitly calls more than one
(ADR-0008).

Providers that do not support tools (Ollama, mock, fake) fall back to keyword
heuristics. This keeps Phase 4 runnable without a paid model and without a torch
install, and it makes the routing tests deterministic (ADR-0017).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ray.agents.registry import ROUTABLE_AGENTS, AgentSpec, get_agent_spec
from ray.llm.base import CompletionRequest, LLMMessage, ToolSpec
from ray.llm.registry import ProviderRegistry

RouterMode = Literal["function_call", "keyword", "fallback"]


@dataclass(frozen=True)
class RoutingDecision:
    """What the orchestrator should run next."""

    agents: tuple[str, ...]
    """Selected specialist agent names, e.g. ("planning",) or ("coding", "planning")."""
    mode: RouterMode
    reason: str
    fan_out: bool = False


_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("teach", "explain", "learn", "how to", "what is", "tutorial"), "learning"),
    (("debug", "code", "programming", "bug", "error", "function", "class", "refactor"), "coding"),
    (("schedule", "plan", "week", "deadline", "calendar", "blocked"), "planning"),
    (("research", "find out", "look up", "what does", "how does"), "research"),
    (("workout", "gym", "exercise", "run", "training", "fitness"), "fitness"),
    (("draft", "content", "post", "blog", "tweet", "thread", "video script"), "content"),
    (("budget", "spend", "expense", "income", "money", "finance", "transaction"), "finance"),
]


def _keyword_route(message: str) -> str | None:
    lowered = message.lower()
    for keywords, agent in _KEYWORD_RULES:
        if any(keyword in lowered for keyword in keywords):
            return agent
    return None


def _delegate_tools(agents: Sequence[AgentSpec]) -> list[ToolSpec]:
    return [
        ToolSpec(
            name=spec.name,
            description=(
                f"Use the {spec.display_name} when: {spec.description}. "
                f"Available tools: {', '.join(spec.tools)}."
            ),
            parameters={"type": "object", "properties": {}},
        )
        for spec in agents
    ]


class ExecutiveRouter:
    """Stateful over one request because it needs the user's agent overrides."""

    def __init__(self, providers: ProviderRegistry) -> None:
        self._providers = providers

    async def decide(
        self,
        message: str,
        *,
        enabled: set[str],
    ) -> RoutingDecision:
        agents = [get_agent_spec(name) for name in ROUTABLE_AGENTS if name in enabled]

        keyword = _keyword_route(message)
        if keyword is not None and any(a.name == keyword for a in agents):
            return RoutingDecision(
                agents=(keyword,), mode="keyword", reason=f"Keyword match: {keyword}."
            )

        if _looks_like_chat(message):
            return RoutingDecision(
                agents=(),
                mode="keyword",
                reason="Social or meta question; Executive answers.",
            )

        request = CompletionRequest(
            messages=[LLMMessage(role="user", content=message)],
            system=_ROUTING_SYSTEM_PROMPT,
            temperature=0.1,
            max_output_tokens=256,
            tools=_delegate_tools(agents),
        )

        try:
            completion = await self._providers.complete(request, role="router")
        except Exception:
            return _fallback(agents, message)

        if completion.tool_calls:
            selected = tuple(
                call.name for call in completion.tool_calls if call.name in {a.name for a in agents}
            )
            fan_out = len(selected) > 1
            final = selected[:2] if fan_out else selected
            if final:
                return RoutingDecision(
                    agents=final,
                    mode="function_call",
                    reason="Model selected specialist(s).",
                    fan_out=fan_out,
                )

        return RoutingDecision(agents=(), mode="function_call", reason="No delegate chosen.")


def _fallback(agents: Sequence[AgentSpec], message: str) -> RoutingDecision:
    keyword = _keyword_route(message)
    if keyword and any(a.name == keyword for a in agents):
        return RoutingDecision(
            agents=(keyword,),
            mode="fallback",
            reason="Routing provider unavailable; keyword fallback.",
        )
    return RoutingDecision(
        agents=(),
        mode="fallback",
        reason="Routing provider unavailable; Executive answers directly.",
    )


def _looks_like_chat(message: str) -> bool:
    lowered = message.lower().strip()
    short_chat_prefixes = (
        "hey",
        "hi",
        "hello",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "good",
    )
    if lowered in ("hey", "hi", "hello"):
        return True
    return lowered.startswith(short_chat_prefixes) and len(lowered) < 30


_ROUTING_SYSTEM_PROMPT = (
    "You are the Executive Agent of Ray, a personal AI assistant. "
    "Pick the right specialist for the user's request. "
    "Call one or two delegate functions. If the message is a greeting, thanks, or a "
    "question about yourself, do not call any delegate — answer directly. "
    "Be decisive: most requests fit one specialist."
)
