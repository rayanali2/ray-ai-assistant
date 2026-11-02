import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ray.config import get_settings
from ray.db.models import CalendarEvent
from ray.domain.enums import EventSource, IntegrationType
from ray.integrations.calendar import GoogleCalendarAdapter
from ray.integrations.google_auth import get_google_oauth
from ray.schemas import CalendarEventCreate, CalendarEventRead, CalendarEventUpdate
from ray.services import integration_service
from ray.services.errors import InvalidEventError


async def list_events(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[CalendarEventRead]:
    stmt = select(CalendarEvent).where(CalendarEvent.user_id == user_id)
    # Overlap, not containment: an event that started this morning and runs into
    # this afternoon still belongs in "today".
    if end is not None:
        stmt = stmt.where(CalendarEvent.start_time < end)
    if start is not None:
        stmt = stmt.where(CalendarEvent.end_time > start)
    stmt = stmt.order_by(CalendarEvent.start_time.asc()).limit(limit)
    result = await session.execute(stmt)
    return [CalendarEventRead.model_validate(e) for e in result.scalars()]


async def dashboard_events(
    session: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
) -> list[CalendarEventRead]:
    events = await list_events(session, user_id, start=start, end=end)
    if get_google_oauth().status() != "connected":
        return events
    adapter = await integration_service.resolve_adapter(
        session,
        user_id,
        IntegrationType.CALENDAR,
        "google",
        fallback=integration_service.IntegrationAdapterConfig(
            type=IntegrationType.CALENDAR, provider="google"
        ),
    )
    if not isinstance(adapter, GoogleCalendarAdapter):
        return events
    result = await adapter.list_events(start.isoformat(), end.isoformat())
    if result.ok:
        for item in result.data["events"]:
            if item.get("status") == "cancelled":
                continue
            try:

                def event_time(value: dict[str, str]) -> datetime:
                    if "dateTime" in value:
                        return datetime.fromisoformat(value["dateTime"])
                    return datetime.fromisoformat(value["date"]).replace(
                        tzinfo=ZoneInfo(value.get("timeZone", get_settings().user_timezone))
                    )

                events.append(
                    CalendarEventRead(
                        id=uuid.uuid5(
                            uuid.NAMESPACE_URL, f"google:{adapter.calendar_id}:{item['id']}"
                        ),
                        title=item.get("summary", "(Untitled)"),
                        description=item.get("description", ""),
                        start_time=event_time(item["start"]),
                        end_time=event_time(item["end"]),
                        location=item.get("location"),
                        source=EventSource.GOOGLE,
                        external_id=item["id"],
                        task_id=None,
                    )
                )
            except (KeyError, ValueError):
                continue
    return sorted(events, key=lambda event: event.start_time)


async def get_event(
    session: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID
) -> CalendarEventRead | None:
    stmt = select(CalendarEvent).where(
        CalendarEvent.id == event_id, CalendarEvent.user_id == user_id
    )
    event = (await session.execute(stmt)).scalar_one_or_none()
    return CalendarEventRead.model_validate(event) if event is not None else None


async def create_event(
    session: AsyncSession, user_id: uuid.UUID, data: CalendarEventCreate
) -> CalendarEventRead:
    """Create a locally-owned event.

    ``LocalCalendar`` is the default calendar (ADR-0010); a synced Google event is
    never created here, which is why ``source`` is not a parameter.
    """
    if data.end_time <= data.start_time:
        raise InvalidEventError("An event must end after it starts.")
    event = CalendarEvent(user_id=user_id, source=EventSource.RAY, **data.model_dump())
    session.add(event)
    await session.flush()
    return CalendarEventRead.model_validate(event)


async def update_event(
    session: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID, data: CalendarEventUpdate
) -> CalendarEventRead | None:
    stmt = select(CalendarEvent).where(
        CalendarEvent.id == event_id, CalendarEvent.user_id == user_id
    )
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        return None

    fields = data.model_dump(exclude_unset=True)
    if {"start_time", "end_time"} <= set(fields.keys()):
        if fields["end_time"] <= fields["start_time"]:
            raise InvalidEventError("An event must end after it starts.")
    elif "end_time" in fields and event.start_time is not None:
        if fields["end_time"] <= event.start_time:
            raise InvalidEventError("An event must end after it starts.")
    elif "start_time" in fields and event.end_time is not None:
        if event.end_time <= fields["start_time"]:
            raise InvalidEventError("An event must end after it starts.")

    for field, value in fields.items():
        setattr(event, field, value)

    await session.flush()
    await session.refresh(event)
    return CalendarEventRead.model_validate(event)


async def delete_event(session: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    stmt = select(CalendarEvent).where(
        CalendarEvent.id == event_id, CalendarEvent.user_id == user_id
    )
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        return False
    await session.delete(event)
    return True


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _ics_dt(dt: datetime) -> str:
    """Format a datetime as UTC ICS timestamp."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def export_ics(events: list[CalendarEventRead]) -> str:
    """Build a minimal VCALENDAR from local events."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ray//EN"]
    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.id}@ray.local",
                f"DTSTAMP:{_ics_dt(datetime.now(UTC))}",
                f"DTSTART:{_ics_dt(event.start_time)}",
                f"DTEND:{_ics_dt(event.end_time)}",
                f"SUMMARY:{_ics_escape(event.title)}",
            ]
        )
        if event.description:
            lines.append(f"DESCRIPTION:{_ics_escape(event.description)}")
        if event.location:
            lines.append(f"LOCATION:{_ics_escape(event.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def import_ics(ics_data: str) -> list[CalendarEventCreate]:
    """Parse a minimal ICS feed into create requests.

    This is intentionally simple: it reads BEGIN:VEVENT blocks and extracts the
    fields Ray cares about. Complex recurrence rules are ignored; an external
    calendar is a mirror, not a master.
    """
    events: list[CalendarEventCreate] = []
    current: dict[str, str] = {}
    in_event = False

    for raw in ics_data.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT":
            in_event = False
            title = current.get("SUMMARY", "Imported event")
            description = current.get("DESCRIPTION", "")
            location = current.get("LOCATION")
            try:
                start = _parse_ics_dt(current["DTSTART"])
                end = _parse_ics_dt(current["DTEND"])
            except KeyError:
                continue
            events.append(
                CalendarEventCreate(
                    title=title,
                    description=description,
                    start_time=start,
                    end_time=end,
                    location=location,
                )
            )
        elif in_event and ":" in line:
            key, value = line.split(":", 1)
            if key.startswith("DTSTART") or key.startswith("DTEND"):
                key = key.split(";")[0]
            current[key] = value

    return events


def _parse_ics_dt(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if "T" in value:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
