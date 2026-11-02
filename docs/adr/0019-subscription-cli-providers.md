# ADR-0019 — Personal subscription CLI providers

## Status

Accepted.

## Decision

Support `claude_cli` (official Claude Code) and `codex_cli` (official OpenAI Codex)
as optional personal-use model providers. Users install the official CLIs and sign
in themselves using their eligible Claude Pro / ChatGPT Plus account. Subscriptions
do not include API keys; these adapters use the CLI's own authentication, never
extract credentials or proxy undocumented subscription endpoints. Eligibility,
usage limits, and vendor terms still apply; this is not a multi-user API service.

Prompts/history are sent over stdin to isolated temporary working directories.
Claude runs in print mode with tools, MCP, hooks, skills and persistence disabled;
Codex runs ephemeral `exec --json` in a read-only sandbox, ignoring user config.
Codex can still use its read-only capabilities: a temporary cwd is not a guarantee
of filesystem privacy. Neither adapter exposes Ray tool calling. Specialist agents
can answer without tool calls, but cannot perform Ray tool actions via these models.

Claude text deltas come from `stream_event/content_block_delta/text_delta` and its
final result is only used when no deltas arrived. Codex emits completed
`item.completed/agent_message` items, not token deltas; reasoning/tool items are ignored.
Formats and flags were checked against Claude Code 2.1.316 / Codex 0.166.0 help and
the official [Claude](https://code.claude.com/docs/en/headless) and
[Codex](https://developers.openai.com/codex/noninteractive) noninteractive docs.

Missing binaries, login errors, malformed/empty output, nonzero exits and bounded
timeouts are retryable. Existing registry semantics prohibit fallback once any text
has been streamed. Processes are reaped on timeout/cancellation; raw diagnostics
are not exposed because they may contain sensitive data.

`RAY_LLM_FALLBACK_PROVIDER` accepts an ordered CSV list (single values remain valid);
duplicates are removed and mock is always last. `doctor` probes login status without
generation or making optional CLI availability affect its exit code.
