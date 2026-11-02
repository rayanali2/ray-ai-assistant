"""Quota delays from Google's RetryInfo and human-readable quota messages."""

import json
import math
import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _duration(value: str) -> float:
    units = {"h": 3600, "m": 60, "s": 1}
    return sum(
        float(number) * units[unit]
        for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", value.lower())
    )


def quota_delay(details: object, now: datetime | None = None) -> tuple[float, str]:
    """Return seconds and daily/minute/unknown scope, without exposing API bodies."""
    message = json.dumps(details, default=str)
    daily = bool(re.search(r"per[_\s-]?day|daily", message, re.IGNORECASE))
    minute = bool(re.search(r"per[_\s-]?minute", message, re.IGNORECASE))
    scope = "daily" if daily else "per-minute" if minute else "rate"
    delays: list[float] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            delay = value.get("retryDelay")
            if isinstance(delay, str):
                delays.append(_duration(delay))
            elif isinstance(delay, dict):
                try:
                    delays.append(
                        float(delay.get("seconds", 0)) + float(delay.get("nanos", 0)) / 1e9
                    )
                except (ValueError, TypeError):
                    pass
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(details)
    for match in re.finditer(r"retry in\s+((?:\d+(?:\.\d+)?\s*[hms]\s*)+)", message, re.IGNORECASE):
        delays.append(_duration(match.group(1)))
    valid = [delay for delay in delays if math.isfinite(delay) and delay > 0]
    if valid:
        return max(valid), scope
    if daily:
        current = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/Los_Angeles"))
        reset = datetime.combine(current.date() + timedelta(days=1), time(), current.tzinfo)
        return (reset.astimezone(UTC) - current.astimezone(UTC)).total_seconds(), scope
    return 60, scope
