"""Cloud productivity tools use the same approval gate as local writes."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from ray.domain.enums import IntegrationType
from ray.integrations.calendar import GoogleCalendarAdapter
from ray.integrations.knowledge import NotionAdapter
from ray.services import integration_service
from ray.services.errors import ServiceError
from ray.tools.manager import Tool, ToolContext


def _required(args: dict[str, object], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(f"{key} is required.")
    return value


def _handler(
    provider: str, operation: str
) -> Callable[[ToolContext, dict[str, object]], Awaitable[dict[str, object]]]:
    async def call(ctx: ToolContext, args: dict[str, object]) -> dict[str, object]:
        kind = IntegrationType.CALENDAR if provider == "google" else IntegrationType.KNOWLEDGE
        adapter = await integration_service.resolve_adapter(
            ctx.session,
            ctx.user_id,
            kind,
            provider,
            fallback=integration_service.IntegrationAdapterConfig(type=kind, provider=provider),
        )
        if isinstance(adapter, GoogleCalendarAdapter):
            if operation == "list":
                start, end = _required(args, "start"), _required(args, "end")
                first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
                if first.tzinfo is None or last.tzinfo is None or last <= first:
                    raise ServiceError("Use an increasing RFC3339 range with UTC offsets.")
                result = await adapter.list_events(start, end)
            elif operation == "delete":
                result = await adapter.delete_event(_required(args, "event_id"))
            else:
                event = args.get("event")
                if not isinstance(event, dict) or not event:
                    raise ServiceError("event must be a non-empty Google Calendar event object.")
                result = (
                    await adapter.create_event(event)
                    if operation == "create"
                    else await adapter.update_event(_required(args, "event_id"), event)
                )
        elif isinstance(adapter, NotionAdapter):
            if operation == "search":
                object_type = str(args.get("object_type", ""))
                if object_type not in ("", "page", "database"):
                    raise ServiceError("object_type must be page or database.")
                result = await adapter.search(str(args.get("query", "")), object_type)
            elif operation == "read":
                result = await adapter.read_page(_required(args, "page_id"))
            elif operation == "append":
                result = await adapter.append_page(
                    _required(args, "page_id"), _required(args, "content")
                )
            else:
                parent_type = str(args.get("parent_type", "page_id"))
                if parent_type not in ("page_id", "database_id"):
                    raise ServiceError("parent_type must be page_id or database_id.")
                result = await adapter.create_page(
                    _required(args, "parent_id"),
                    _required(args, "title"),
                    str(args.get("content", "")),
                    parent_type,
                    str(args.get("title_property", "Name")),
                )
        else:
            raise ServiceError(f"{provider} integration is disabled or unavailable.")
        if not result.ok:
            raise ServiceError(result.error)
        return result.data

    return call


def _tool(
    provider: str,
    operation: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    *,
    write: bool = False,
) -> Tool:
    name = f"{'google_calendar' if provider == 'google' else provider}.{operation}"
    return Tool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required},
        handler=_handler(provider, operation),
        side_effect=write,
        standing_allow_eligible=False,
        summarise=lambda args: f"{description}: {args}",
    )


_TEXT = {"type": "string"}
_EVENT = {
    "type": "object",
    "description": (
        "Google event fields: summary, description, location, start/end "
        "({dateTime: RFC3339, timeZone: IANA} or {date: YYYY-MM-DD} for all-day). "
        "Updates contain only changed fields."
    ),
}
CLOUD_TOOLS = (
    _tool(
        "google",
        "list",
        "List Google Calendar events in a date/time range",
        {"start": _TEXT, "end": _TEXT},
        ["start", "end"],
    ),
    _tool(
        "google",
        "create",
        "Create a Google Calendar event",
        {"event": _EVENT},
        ["event"],
        write=True,
    ),
    _tool(
        "google",
        "update",
        "Update a Google Calendar event",
        {"event_id": _TEXT, "event": _EVENT},
        ["event_id", "event"],
        write=True,
    ),
    _tool(
        "google",
        "delete",
        "Delete a Google Calendar event",
        {"event_id": _TEXT},
        ["event_id"],
        write=True,
    ),
    _tool(
        "notion",
        "search",
        "Search shared Notion pages and databases",
        {"query": _TEXT, "object_type": {"type": "string", "enum": ["page", "database"]}},
        [],
    ),
    _tool("notion", "read", "Read a Notion page as Markdown", {"page_id": _TEXT}, ["page_id"]),
    _tool(
        "notion",
        "create",
        "Create a Notion page under a page or database",
        {
            "parent_id": _TEXT,
            "title": _TEXT,
            "content": _TEXT,
            "parent_type": {
                "type": "string",
                "enum": ["page_id", "database_id"],
                "default": "page_id",
            },
            "title_property": {
                "type": "string",
                "description": "Database title column name (default Name).",
            },
        },
        ["parent_id", "title"],
        write=True,
    ),
    _tool(
        "notion",
        "append",
        "Request approval to append text to an existing Notion page. Calling this tool "
        "queues a pending approval; no content is written until the user approves in Ray.",
        {"page_id": _TEXT, "content": _TEXT},
        ["page_id", "content"],
        write=True,
    ),
)
