"""Tools backed by external integrations (Phase 5).

These tools bridge the Tool Manager to the adapter layer. Each tool resolves the
relevant integration, calls the adapter, and returns a normalised result that the
agent can turn into an answer. Credentials are never exposed to the agent
(ADR-0010, docs/12).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ray.domain.enums import IntegrationType
from ray.integrations.files import LocalFileAdapter
from ray.integrations.github import GitHubAdapter
from ray.integrations.knowledge import ObsidianAdapter
from ray.services import calendar_service, integration_service
from ray.services.errors import ServiceError
from ray.tools.cloud_tools import CLOUD_TOOLS
from ray.tools.manager import Tool, ToolContext


def _string(description: str, **extra: object) -> dict[str, object]:
    return {"type": "string", "description": description, **extra}


async def _github_adapter(ctx: ToolContext) -> GitHubAdapter:
    """Resolve the user's GitHub integration or fall back to an env token."""
    fallback = integration_service.IntegrationAdapterConfig(
        type=IntegrationType.GITHUB,
        provider="github",
        credentials_reference="env:RAY_GITHUB_TOKEN",
    )
    adapter = await integration_service.resolve_adapter(
        ctx.session, ctx.user_id, IntegrationType.GITHUB, "github", fallback=fallback
    )
    if isinstance(adapter, GitHubAdapter):
        return adapter
    raise ServiceError("GitHub is not available.")


def _github_repo(arguments: dict[str, object]) -> str:
    repo = str(arguments.get("repo", "")).strip()
    if not repo:
        raise ServiceError("repo is required (owner/name).")
    return repo


async def _github_read_repo(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    adapter = await _github_adapter(ctx)
    result = await adapter.get_repo(_github_repo(arguments))
    return _normalise(result)


async def _github_read_tree(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    adapter = await _github_adapter(ctx)
    result = await adapter.get_tree(_github_repo(arguments), ref=str(arguments.get("ref", "HEAD")))
    return _normalise(result)


async def _github_read_file(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    adapter = await _github_adapter(ctx)
    path = str(arguments.get("path", "")).strip()
    if not path:
        raise ServiceError("path is required.")
    result = await adapter.get_file(
        _github_repo(arguments), path=path, ref=str(arguments.get("ref", "HEAD"))
    )
    return _normalise(result)


async def _github_read_issues(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    adapter = await _github_adapter(ctx)
    result = await adapter.get_issues(
        _github_repo(arguments), state=str(arguments.get("state", "open"))
    )
    return _normalise(result)


async def _github_read_commits(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    adapter = await _github_adapter(ctx)
    limit = int(str(arguments.get("limit") or 10))
    result = await adapter.get_commits(_github_repo(arguments), limit=limit)
    return _normalise(result)


def _normalise(result: Any) -> dict[str, object]:
    """AdapterResult already has a safe shape; raw dicts are wrapped for the agent."""
    if hasattr(result, "ok"):
        return {"ok": result.ok, **result.data, "error": result.error or ""}
    return {"ok": True, **result}


async def _files_read(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    path = str(arguments.get("path", "")).strip()
    if not path:
        raise ServiceError("path is required.")
    adapter = await integration_service.resolve_adapter(
        ctx.session, ctx.user_id, IntegrationType.FILES, "local"
    )
    if not isinstance(adapter, LocalFileAdapter):
        raise ServiceError("No file integration configured. Add a local files integration.")
    result = await adapter.read(path)
    return _normalise(result)


async def _knowledge_search(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ServiceError("query is required.")
    adapter = await integration_service.resolve_adapter(
        ctx.session, ctx.user_id, IntegrationType.KNOWLEDGE, "obsidian"
    )
    if not isinstance(adapter, ObsidianAdapter):
        raise ServiceError("No Obsidian vault configured. Add a knowledge integration.")
    result = await adapter.search(query, limit=int(str(arguments.get("limit") or 10)))
    return _normalise(result)


async def _knowledge_read(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    path = str(arguments.get("path", "")).strip()
    if not path:
        raise ServiceError("path is required.")
    adapter = await integration_service.resolve_adapter(
        ctx.session, ctx.user_id, IntegrationType.KNOWLEDGE, "obsidian"
    )
    if not isinstance(adapter, ObsidianAdapter):
        raise ServiceError("No Obsidian vault configured. Add a knowledge integration.")
    result = await adapter.get_note(path)
    return _normalise(result)


async def _calendar_ics_export(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    days = int(str(arguments.get("days") or 30))
    start = datetime.now(UTC)
    events = await calendar_service.list_events(
        ctx.session, ctx.user_id, start=start, end=start + timedelta(days=days)
    )
    ics = calendar_service.export_ics(events)
    return {"ics": ics, "count": len(events)}


async def _calendar_ics_import(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    ics_data = str(arguments.get("ics_data", ""))
    if not ics_data:
        raise ServiceError("ics_data is required.")
    creates = calendar_service.import_ics(ics_data)
    created: list[dict[str, object]] = []
    for data in creates:
        event = await calendar_service.create_event(ctx.session, ctx.user_id, data)
        created.append(event.model_dump(mode="json"))
    return {"created": created, "count": len(created)}


INTEGRATION_TOOLS: tuple[Tool, ...] = (
    *CLOUD_TOOLS,
    Tool(
        name="github.read_repo",
        description="Read metadata for a GitHub repository. repo must be 'owner/name'.",
        parameters={
            "type": "object",
            "properties": {"repo": _string("Repository as owner/name.")},
            "required": ["repo"],
        },
        handler=_github_read_repo,
    ),
    Tool(
        name="github.read_tree",
        description="List files in a GitHub repository. repo must be 'owner/name'.",
        parameters={
            "type": "object",
            "properties": {
                "repo": _string("Repository as owner/name."),
                "ref": _string("Branch, tag or commit hash.", default="HEAD"),
            },
            "required": ["repo"],
        },
        handler=_github_read_tree,
    ),
    Tool(
        name="github.read_file",
        description="Read the contents of a file from a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": _string("Repository as owner/name."),
                "path": _string("File path in the repository."),
                "ref": _string("Branch, tag or commit hash.", default="HEAD"),
            },
            "required": ["repo", "path"],
        },
        handler=_github_read_file,
    ),
    Tool(
        name="github.read_issues",
        description="List issues for a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": _string("Repository as owner/name."),
                "state": _string(
                    "open, closed or all.", enum=["open", "closed", "all"], default="open"
                ),
            },
            "required": ["repo"],
        },
        handler=_github_read_issues,
    ),
    Tool(
        name="github.read_commits",
        description="Read recent commits for a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": _string("Repository as owner/name."),
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["repo"],
        },
        handler=_github_read_commits,
    ),
    Tool(
        name="files.read",
        description="Read a file or list a directory inside an allow-listed local path.",
        parameters={
            "type": "object",
            "properties": {"path": _string("File or directory path.")},
            "required": ["path"],
        },
        handler=_files_read,
    ),
    Tool(
        name="knowledge.search",
        description="Search the connected Obsidian vault for a query.",
        parameters={
            "type": "object",
            "properties": {
                "query": _string("What to search for."),
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        handler=_knowledge_search,
    ),
    Tool(
        name="knowledge.read",
        description="Read one note from the connected Obsidian vault by relative path.",
        parameters={
            "type": "object",
            "properties": {"path": _string("Relative path inside the vault.")},
            "required": ["path"],
        },
        handler=_knowledge_read,
    ),
    Tool(
        name="calendar.ics_export",
        description="Export upcoming calendar events to an ICS string.",
        parameters={
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
        },
        handler=_calendar_ics_export,
    ),
    Tool(
        name="calendar.ics_import",
        description="Import events from an ICS string. Adds them to the local calendar.",
        parameters={
            "type": "object",
            "properties": {"ics_data": _string("The full ICS calendar data.")},
            "required": ["ics_data"],
        },
        handler=_calendar_ics_import,
        side_effect=True,
        summarise=lambda args: "Import calendar events from ICS data",
    ),
)
