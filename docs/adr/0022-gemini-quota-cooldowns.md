# ADR-0022 — Per-model Gemini quota cooldowns

## Status

Accepted. Extends ADR-0001 and ADR-0015; records behavior merged in PR #26.

## Context

Some Gemini free-tier projects allow only 20 requests/day for the primary model.
Retrying every turn wastes requests and hides why Ray eventually answers from mock.
Traces that label the configured primary instead of the answering fallback are misleading.

## Decision

Parse HTTP 429 RetryInfo and human-readable retry durations; distinguish daily and
per-minute quotas. Track cooldowns per model using a monotonic clock. If no delay
is supplied, daily limits wait for midnight Pacific and other limits wait 60 seconds.
Try the ordered `RAY_GEMINI_FALLBACK_MODELS` CSV on quota exhaustion; default to
`gemini-flash-lite-latest`, allow an empty value to disable. Skip cooled models and
skip the Gemini provider entirely when all its models are cooling down.

Expose quota/reset details through health diagnostics and HUD telemetry. Prepend
quota-related mock notices only for agent responses, never router/structured output.
Record actual-answer provider attribution after execution, with task-local tracking
separate from the process-wide last-answer provider shown in health.
Never switch models/providers after streamed output has begun.

## Alternatives considered

* Retrying Gemini every turn wastes quota and increases latency.
* Sleeping until reset would block chat instead of using available fallbacks.
* Persisting cooldowns adds state management not needed for this local process.

## Consequences

Cooldowns clear on restart. Available models and higher quotas depend on the user's
project; Flash Lite is not a guaranteed quota entitlement. Router/tool/extraction
calls also consume quota. Mocked tests cover parsing, expiry, fallback, attribution
and unmodified router JSON; live quota limits remain an account-specific check.
