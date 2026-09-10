"""Google AI Studio adapter — Ray's default (ADR-0001).

The key is read from the environment and never logged. Absence of a key is not an
error here: the provider reports itself unconfigured and the registry picks the
fallback.
"""

from collections.abc import AsyncIterator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ray.llm.base import (
    Chunk,
    Completion,
    CompletionRequest,
    LLMProvider,
    ProviderInfo,
    ProviderRequestError,
    ProviderUnavailableError,
    RateLimitedError,
    ToolCall,
)

# The alias, not a pinned version: pinned free-tier models get their quota
# retired, and an alias keeps working when that happens.
DEFAULT_MODEL = "gemini-flash-latest"

# Gemini calls the assistant "model"; every other provider we support does not.
_ROLE_MAP = {"user": "user", "assistant": "model"}


def _to_contents(request: CompletionRequest) -> list[types.Content]:
    return [
        types.Content(
            role=_ROLE_MAP.get(message.role, "user"),
            parts=[types.Part.from_text(text=message.content)],
        )
        for message in request.messages
        if message.role != "system"
    ]


def _to_tools(request: CompletionRequest) -> list[types.Tool] | None:
    if not request.tools:
        return None
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    # Gemini validates the schema, so a tool with no arguments still
                    # needs a well-formed empty object.
                    parameters=types.Schema(**tool.parameters),
                )
                for tool in request.tools
            ]
        )
    ]


def _to_config(request: CompletionRequest) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=request.system or None,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        tools=_to_tools(request),
    )


def _text_of(response: types.GenerateContentResponse) -> str:
    """``response.text`` warns and can return None when the model answered with a
    function call instead of prose, which is the normal case for a routing call."""
    parts = response.candidates[0] if response.candidates else None
    if parts is None or parts.content is None:
        return ""
    return "".join(part.text for part in parts.content.parts or [] if part.text)


def _translate(exc: genai_errors.APIError) -> Exception:
    """Map vendor errors onto Ray's retryable/not-retryable distinction."""
    status = exc.code or 0
    if status == 429:
        return RateLimitedError(str(exc), provider="gemini")
    # 404 means the configured model does not exist for this key. That is a
    # configuration problem, and the useful response is the same as for an outage:
    # answer from the fallback instead of failing the turn.
    if status in (404, 503) or status >= 500 or status == 0:
        return ProviderUnavailableError(str(exc), provider="gemini")
    return ProviderRequestError(str(exc), provider="gemini")


# Default request deadline. 15 seconds is enough for a healthy Gemini response
# while preventing a hung/overloaded model from blocking the fallback chain.
DEFAULT_TIMEOUT_MS = 15_000


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry_attempts: int = 1,
    ) -> None:
        self._model = model
        # Disable SDK-level retries on 5xx/timeout: the registry already handles
        # fallback across providers. Retrying the same overloaded endpoint is what
        # produces the 60-90 second hangs for a simple greeting.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=retry_attempts),
                # The SDK sets X-Server-Timeout from the timeout above; raise the
                # server-side ceiling so streaming responses are not truncated at 15s.
                headers={"X-Server-Timeout": "120"},
            ),
        )

    async def complete(self, request: CompletionRequest) -> Completion:
        # Use the streaming endpoint even for "non-streaming" tool-calling.
        # generate_content (non-stream) waits for the full response and, under
        # load, hangs for 30-90s before returning a 503. generate_content_stream
        # returns the first token/error quickly and lets us collect tool calls
        # and prose as they arrive, so the fallback chain activates in seconds.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = None
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=_to_contents(request),
                config=_to_config(request),
            )
            async for event in stream:
                if event.usage_metadata:
                    usage = event.usage_metadata
                if event.text:
                    text_parts.append(event.text)
                if event.function_calls:
                    tool_calls.extend(
                        ToolCall(name=call.name or "", arguments=dict(call.args or {}))
                        for call in event.function_calls
                    )
        except genai_errors.APIError as exc:
            raise _translate(exc) from exc

        return Completion(
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
            provider=self.name,
            model=self._model,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[Chunk]:
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=_to_contents(request),
                config=_to_config(request),
            )
            async for event in stream:
                if event.text:
                    yield Chunk(text=event.text)
        except genai_errors.APIError as exc:
            raise _translate(exc) from exc
        yield Chunk(is_final=True)

    def info(self) -> ProviderInfo:
        return ProviderInfo(name=self.name, model=self._model, configured=True)

    def supports_tools(self) -> bool:
        return True
