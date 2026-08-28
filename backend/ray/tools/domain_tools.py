"""Specialist agent tools for Phase 9 domains: fitness, content, finance.

These tools reuse the Task table as a lightweight local journal for each domain.
Each domain stores records as tasks with a fixed category string and a JSON payload
in the description, so no new database tables are required for Phase 9.  The Task
shape already supports title, description, deadline, status, and priority; the JSON
payload holds the remaining domain-specific fields.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from ray.domain.enums import TaskPriority
from ray.schemas import TaskCreate
from ray.services import task_service
from ray.services.errors import ServiceError
from ray.tools.manager import Tool, ToolContext


def _string(description: str, **extra: object) -> dict[str, object]:
    return {"type": "string", "description": description, **extra}


def _number(description: str, **extra: object) -> dict[str, object]:
    return {"type": "number", "description": description, **extra}


def _iso_date(description: str, **extra: object) -> dict[str, object]:
    return _string(description, **extra)


def _optional_date(arguments: dict[str, object], key: str) -> datetime | None:
    raw = arguments.get(key)
    if raw in (None, ""):
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ServiceError(f"{key} must be an ISO 8601 timestamp.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_to_record(task: Any, payload_fields: tuple[str, ...]) -> dict[str, object]:
    """Turn a TaskRead into a domain record, merging the JSON description payload."""
    data: dict[str, object] = {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "deadline": task.deadline.isoformat() if task.deadline else None,
    }
    payload: dict[str, object] | None = None
    if task.description:
        try:
            payload = json.loads(task.description)
        except json.JSONDecodeError:
            payload = {"notes": task.description}
    if isinstance(payload, dict):
        for field in payload_fields:
            if field in payload:
                data[field] = payload[field]
    return data


async def _tasks_in_category(session: Any, user_id: uuid.UUID, category: str) -> list[Any]:
    return await task_service.list_tasks(
        session, user_id, include_done=True, status=None, project_id=None
    )


def _filter_category(tasks: list[Any], category: str) -> list[Any]:
    return [t for t in tasks if t.category == category]


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------


async def _fitness_log_workout(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ServiceError("title is required.")
    date = _optional_date(arguments, "date") or datetime.now(UTC)
    exercises = _list_str(arguments.get("exercises"))
    notes = str(arguments.get("notes", ""))
    payload = {
        "type": "workout",
        "date": date.isoformat(),
        "exercises": exercises,
        "notes": notes,
    }
    task = await task_service.create_task(
        ctx.session,
        ctx.user_id,
        TaskCreate(
            title=title,
            description=json.dumps(payload),
            category="fitness",
            priority=TaskPriority.MEDIUM,
        ),
    )
    return {"record": _task_to_record(task, ("date", "exercises", "notes"))}


async def _fitness_list_workouts(
    ctx: ToolContext, _arguments: dict[str, object]
) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    workouts = _filter_category(all_tasks, "fitness")
    workouts.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
    return {
        "workouts": [_task_to_record(w, ("date", "exercises", "notes")) for w in workouts],
        "count": len(workouts),
    }


async def _fitness_get_progress(
    ctx: ToolContext, _arguments: dict[str, object]
) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    workouts = _filter_category(all_tasks, "fitness")
    completed = [w for w in workouts if w.status == "done"]
    return {
        "total_workouts": len(workouts),
        "completed_workouts": len(completed),
        "completion_rate": round(len(completed) / len(workouts), 2) if workouts else 0.0,
        "recent_workouts": [
            _task_to_record(w, ("date", "exercises", "notes")) for w in workouts[-7:]
        ],
    }


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


async def _content_create_idea(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ServiceError("title is required.")
    content_format = str(arguments.get("format", "")).strip()
    notes = str(arguments.get("notes", "")).strip()
    payload: dict[str, object] = {"type": "content_idea"}
    if content_format:
        payload["format"] = content_format
    if notes:
        payload["notes"] = notes
    task = await task_service.create_task(
        ctx.session,
        ctx.user_id,
        TaskCreate(
            title=title,
            description=json.dumps(payload) if payload else "",
            category="content",
            priority=TaskPriority.MEDIUM,
        ),
    )
    return {"record": _task_to_record(task, ("format", "notes"))}


async def _content_create_draft(
    ctx: ToolContext, arguments: dict[str, object]
) -> dict[str, object]:
    title = str(arguments.get("title", "")).strip()
    body = str(arguments.get("body", "")).strip()
    if not title:
        raise ServiceError("title is required.")
    payload = {"type": "content_draft", "body": body}
    task = await task_service.create_task(
        ctx.session,
        ctx.user_id,
        TaskCreate(
            title=title,
            description=json.dumps(payload),
            category="content_draft",
            priority=TaskPriority.MEDIUM,
        ),
    )
    return {"record": _task_to_record(task, ("body",))}


async def _content_list_ideas(ctx: ToolContext, _arguments: dict[str, object]) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    ideas = _filter_category(all_tasks, "content")
    return {
        "ideas": [_task_to_record(i, ("format", "notes")) for i in ideas],
        "count": len(ideas),
    }


async def _content_list_drafts(
    ctx: ToolContext, _arguments: dict[str, object]
) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    drafts = _filter_category(all_tasks, "content_draft")
    return {
        "drafts": [_task_to_record(d, ("body",)) for d in drafts],
        "count": len(drafts),
    }


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------


async def _finance_record_transaction(
    ctx: ToolContext, arguments: dict[str, object]
) -> dict[str, object]:
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ServiceError("title is required.")
    raw_amount = arguments.get("amount")
    if raw_amount is None:
        raise ServiceError("amount is required.")
    try:
        amount = float(str(raw_amount))
    except (TypeError, ValueError) as exc:
        raise ServiceError("amount must be a number.") from exc
    currency = str(arguments.get("currency", "USD")).strip().upper() or "USD"
    txn_type = str(arguments.get("type", "expense")).strip().lower()
    if txn_type not in ("income", "expense"):
        txn_type = "expense"
    tags = _list_str(arguments.get("tags"))
    date = _optional_date(arguments, "date") or datetime.now(UTC)
    payload = {
        "type": "transaction",
        "amount": amount,
        "currency": currency,
        "transaction_type": txn_type,
        "tags": tags,
        "date": date.isoformat(),
    }
    # Finance records are sensitive; mark as high priority so the user sees them
    # clearly when reviewing recent items, but keep them local.
    task = await task_service.create_task(
        ctx.session,
        ctx.user_id,
        TaskCreate(
            title=title,
            description=json.dumps(payload),
            category="finance",
            priority=TaskPriority.HIGH,
        ),
    )
    return {
        "record": _task_to_record(task, ("amount", "currency", "transaction_type", "tags", "date"))
    }


async def _finance_list_transactions(
    ctx: ToolContext, arguments: dict[str, object]
) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    transactions = _filter_category(all_tasks, "finance")
    tag = str(arguments.get("tag", "")).strip().lower()
    if tag:
        transactions = [
            t
            for t in transactions
            if tag in str(json.loads(t.description).get("tags", [])).lower()
            if t.description
        ]
    transactions.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
    return {
        "transactions": [
            _task_to_record(t, ("amount", "currency", "transaction_type", "tags", "date"))
            for t in transactions
        ],
        "count": len(transactions),
    }


async def _finance_get_summary(
    ctx: ToolContext, _arguments: dict[str, object]
) -> dict[str, object]:
    all_tasks = await task_service.list_tasks(
        ctx.session, ctx.user_id, include_done=True, status=None, project_id=None
    )
    transactions = _filter_category(all_tasks, "finance")
    by_currency: dict[str, dict[str, float]] = {}
    by_tag: dict[str, float] = {}
    for t in transactions:
        payload: dict[str, Any] | None = None
        if t.description:
            try:
                payload = json.loads(t.description)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        amount = float(payload.get("amount", 0))
        currency = str(payload.get("currency", "USD")).upper()
        txn_type = str(payload.get("transaction_type", "expense"))
        signed = amount if txn_type == "income" else -amount
        by_currency.setdefault(currency, {"income": 0.0, "expense": 0.0})
        if txn_type == "income":
            by_currency[currency]["income"] += amount
        else:
            by_currency[currency]["expense"] += amount
        for tag in _list_str(payload.get("tags")):
            by_tag[tag] = by_tag.get(tag, 0.0) + signed
    return {
        "count": len(transactions),
        "by_currency": {
            c: {k: round(v, 2) for k, v in totals.items()} for c, totals in by_currency.items()
        },
        "by_tag": {k: round(v, 2) for k, v in by_tag.items()},
        "transactions": [
            _task_to_record(t, ("amount", "currency", "transaction_type", "tags", "date"))
            for t in transactions[-50:]
        ],
    }


DOMAIN_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="fitness.log_workout",
        description="Log a workout or fitness session for the user.",
        parameters={
            "type": "object",
            "properties": {
                "title": _string("Short title for the workout, e.g. 'Morning run' or 'Leg day'."),
                "date": _iso_date("When the workout happened. ISO 8601; defaults to now."),
                "exercises": {
                    "type": "array",
                    "description": "List of exercises or activities performed.",
                    "items": {"type": "string"},
                },
                "notes": _string("Freeform notes about the session."),
            },
            "required": ["title"],
        },
        handler=_fitness_log_workout,
        side_effect=True,
        summarise=lambda args: f"Log workout: {args.get('title', '')!r}",
    ),
    Tool(
        name="fitness.list_workouts",
        description="List the user's recent workouts and fitness sessions.",
        parameters={"type": "object", "properties": {}},
        handler=_fitness_list_workouts,
    ),
    Tool(
        name="fitness.get_progress",
        description="Summarise the user's fitness activity and completion rate.",
        parameters={"type": "object", "properties": {}},
        handler=_fitness_get_progress,
    ),
    Tool(
        name="content.create_idea",
        description="Capture a content idea (blog, video, tweet thread, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "title": _string("The content idea in one line."),
                "format": _string("Optional format: blog, video, tweet, thread, etc."),
                "notes": _string("Optional extra detail or outline."),
            },
            "required": ["title"],
        },
        handler=_content_create_idea,
        side_effect=True,
        summarise=lambda args: f"Create content idea: {args.get('title', '')!r}",
    ),
    Tool(
        name="content.list_ideas",
        description="List the user's saved content ideas.",
        parameters={"type": "object", "properties": {}},
        handler=_content_list_ideas,
    ),
    Tool(
        name="content.create_draft",
        description="Create a full content draft with a body.",
        parameters={
            "type": "object",
            "properties": {
                "title": _string("Title of the draft."),
                "body": _string("The draft body text."),
            },
            "required": ["title", "body"],
        },
        handler=_content_create_draft,
        side_effect=True,
        summarise=lambda args: f"Create content draft: {args.get('title', '')!r}",
    ),
    Tool(
        name="content.list_drafts",
        description="List the user's saved content drafts.",
        parameters={"type": "object", "properties": {}},
        handler=_content_list_drafts,
    ),
    Tool(
        name="finance.record_transaction",
        description="Record a personal income or expense transaction. Stored locally.",
        parameters={
            "type": "object",
            "properties": {
                "title": _string("Description of the transaction, e.g. 'Weekly groceries'."),
                "amount": _number("Amount as a positive number."),
                "currency": _string("Currency code like USD, EUR, GBP.", default="USD"),
                "type": _string(
                    "income or expense.", enum=["income", "expense"], default="expense"
                ),
                "tags": {
                    "type": "array",
                    "description": "Tags such as food, transport, salary.",
                    "items": {"type": "string"},
                },
                "date": _iso_date("ISO 8601 date; defaults to now."),
            },
            "required": ["title", "amount"],
        },
        handler=_finance_record_transaction,
        side_effect=True,
        summarise=lambda args: f"Record {args.get('type', 'expense')} {args.get('title', '')!r}",
    ),
    Tool(
        name="finance.list_transactions",
        description="List personal income and expense transactions. Optionally filter by tag.",
        parameters={
            "type": "object",
            "properties": {
                "tag": _string("Optional tag to filter by."),
            },
        },
        handler=_finance_list_transactions,
    ),
    Tool(
        name="finance.get_summary",
        description=(
            "Summarise income, expenses, and spending by tag across all recorded transactions."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_finance_get_summary,
    ),
)
