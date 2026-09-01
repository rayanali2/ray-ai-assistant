"""Base for a specialist agent that uses tools.

Pattern: one non-streaming call *with* tools to collect tool calls, execute them,
then one streaming call *without* tools to generate the answer. This keeps the
final answer streaming and caps tool use at two model calls (ADR-0017).

Specialists subclass this and provide a system prompt and the tool allow-list from
``ray.agents.registry``.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from ray.agents.base import Agent, AgentContext, AgentEvent, AgentFinished, AgentToken, load_prompt
from ray.agents.speech import to_speech
from ray.domain.enums import Modality
from ray.llm.base import CompletionRequest, LLMMessage
from ray.llm.registry import Degradation, ProviderRegistry
from ray.tools.types import ToolResult

MAX_TOOL_ROUNDS = 3


@dataclass
class ToolUsingAgent(Agent, ABC):
    """A specialist with tools."""

    def __init__(
        self,
        providers: ProviderRegistry,
        *,
        temperature: float = 0.7,
        on_degrade: Callable[[Degradation], None] | None = None,
    ) -> None:
        self._providers = providers
        self._temperature = temperature
        self._on_degrade = on_degrade

    @property
    @abstractmethod
    def prompt_name(self) -> str: ...

    @abstractmethod
    def _render_tool_result(self, result: ToolResult) -> str:
        """How the result of a tool call is written into the prompt."""
        ...

    def system_prompt(self, ctx: AgentContext) -> str:
        prompt = load_prompt(self.prompt_name).replace("{user_name}", ctx.user_name)
        if ctx.memories:
            remembered = "\n".join(f"- {m.content}" for m in ctx.memories)
            prompt += f"\n\n## What you remember about {ctx.user_name}\n\n{remembered}"
        if ctx.output_modality is Modality.VOICE:
            prompt += (
                "\n\n## This answer will be spoken aloud\n\n"
                "Keep it short and plain. No code blocks, no tables, no bullet lists, "
                "no markdown syntax — write it the way you would say it."
            )
        return prompt

    async def run(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        conversation: list[LLMMessage] = []

        for _ in range(MAX_TOOL_ROUNDS):
            specs = ctx.tools.specs(self.spec.tools)
            request = CompletionRequest(
                messages=[
                    *ctx.history,
                    LLMMessage(role="user", content=ctx.message),
                    *conversation,
                ],
                system=self.system_prompt(ctx),
                temperature=self._temperature,
                tools=specs,
            )

            try:
                completion = await self._providers.complete(request, on_degrade=self._on_degrade)
            except Exception:
                # Tool-calling unavailable: the agent still tries to answer from context.
                conversation.append(LLMMessage(role="user", content="(Tool lookup failed.)"))
                break

            if not completion.tool_calls:
                break

            for call in completion.tool_calls:
                result = await ctx.tools.call(call.name, call.arguments, allowed=self.spec.tools)
                conversation.append(
                    LLMMessage(role="user", content=self._render_tool_result(result))
                )
                if result.status == "pending_approval":
                    content = (
                        f"I've prepared that action and need your approval to proceed: "
                        f"{result.data.get('summary', call.name)}. "
                        "Approve it below and I'll continue."
                    )
                    yield AgentToken(text=content)
                    yield AgentFinished(content=content, speech_text=to_speech(content))
                    return

        # If no tools were needed and the model already answered, skip the second
        # model call. This avoids the extra latency of a separate final-stream
        # request for simple greetings/questions.
        if not conversation and not completion.tool_calls and completion.text:
            content = completion.text
            yield AgentToken(text=content)
            yield AgentFinished(content=content, speech_text=to_speech(content))
            return

        # Final streaming answer; no tools offered, so the response is prose.
        final_request = CompletionRequest(
            messages=[*ctx.history, LLMMessage(role="user", content=ctx.message), *conversation],
            system=self.system_prompt(ctx),
            temperature=self._temperature,
            tools=(),
        )
        content_parts: list[str] = []
        async for chunk in self._providers.stream(final_request, on_degrade=self._on_degrade):
            if chunk.text:
                content_parts.append(chunk.text)
                yield AgentToken(text=chunk.text)

        content = "".join(content_parts)
        yield AgentFinished(content=content, speech_text=to_speech(content))

    @property
    def name(self) -> str:
        return self.spec.name
