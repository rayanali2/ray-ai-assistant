"""Built-in utility skill: weather, news, web search, reference, and quick math.

Every network call goes through the adapter layer in ``ray.integrations.utility`` so the
agent never holds an HTTP client or an API key.
"""

from __future__ import annotations

import ast
import datetime
import operator
from collections.abc import Callable
from zoneinfo import ZoneInfo

from ray.integrations import utility as utility_adapters
from ray.integrations.base import AdapterResult
from ray.services import user_service
from ray.services.errors import ServiceError
from ray.tools.manager import Tool, ToolContext, ToolManager


def _string(description: str, **extra: object) -> dict[str, object]:
    return {"type": "string", "description": description, **extra}


def _number(description: str, **extra: object) -> dict[str, object]:
    return {"type": "number", "description": description, **extra}


def _normalise(result: AdapterResult) -> dict[str, object]:
    return {"ok": result.ok, **result.data, "error": result.error or ""}


async def _user_timezone(ctx: ToolContext) -> ZoneInfo:
    """Resolve the user's timezone preference, defaulting to UTC."""
    user = await user_service.get_user(ctx.session, ctx.user_id)
    tz_name = "UTC"
    if user and user.preferences:
        value = user.preferences.get("timezone")
        if isinstance(value, str):
            tz_name = value
    try:
        return ZoneInfo(str(tz_name))
    except Exception:
        return ZoneInfo("UTC")


async def _time_now(ctx: ToolContext, _arguments: dict[str, object]) -> dict[str, object]:
    tz = await _user_timezone(ctx)
    now = datetime.datetime.now(tz)
    return {
        "iso": now.isoformat(),
        "time": now.strftime("%I:%M %p %Z").lstrip("0"),
        "date": now.strftime("%A, %d %B %Y"),
        "timezone": str(tz),
    }


async def _date_today(ctx: ToolContext, _arguments: dict[str, object]) -> dict[str, object]:
    tz = await _user_timezone(ctx)
    today = datetime.datetime.now(tz).date()
    return {
        "iso": today.isoformat(),
        "formatted": today.strftime("%A, %d %B %Y"),
        "day_of_week": today.strftime("%A"),
        "timezone": str(tz),
    }


async def _weather_current(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    location = str(arguments.get("location", "")).strip()
    if not location:
        # Fall back to a generic auto-IP location from wttr.in.
        location = "auto"
    result = await utility_adapters.weather_current(location)
    return _normalise(result)


async def _news_headlines(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    query = arguments.get("query")
    result = await utility_adapters.news_headlines(str(query) if query else None)
    return _normalise(result)


async def _web_search(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ServiceError("query is required.")
    result = await utility_adapters.web_search(query)
    return _normalise(result)


async def _wikipedia_summary(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    title = str(arguments.get("title", "")).strip()
    if not title:
        raise ServiceError("title is required.")
    result = await utility_adapters.wikipedia_summary(title)
    return _normalise(result)


async def _dictionary_define(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    word = str(arguments.get("word", "")).strip().lower()
    if not word:
        raise ServiceError("word is required.")
    result = await utility_adapters.dictionary_define(word)
    return _normalise(result)


# A tiny safe-expression evaluator for the calculator.  It supports only numbers and
# arithmetic operators; any attribute access, name reference, or call is rejected.
_ALLOWED_BINOPS: dict[type[ast.AST], Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ServiceError("Only numbers are allowed in calculator expressions.")
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        op = _ALLOWED_BINOPS[type(node.op)]
        return float(op(_eval_node(node.left), _eval_node(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_BINOPS:
        op = _ALLOWED_BINOPS[type(node.op)]
        return float(op(_eval_node(node.operand)))
    raise ServiceError("Only basic arithmetic is supported.")


async def _calculator_compute(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    expression = str(arguments.get("expression", "")).strip()
    if not expression:
        raise ServiceError("expression is required.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ServiceError(f"Could not parse expression: {exc}") from exc
    try:
        value = _eval_node(tree)
    except (ServiceError, ZeroDivisionError, OverflowError) as exc:
        return {"ok": False, "expression": expression, "error": str(exc)}
    return {"ok": True, "expression": expression, "value": value}


_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="time.now",
        description="Get the current time in the user's preferred timezone.",
        parameters={"type": "object", "properties": {}},
        handler=_time_now,
    ),
    Tool(
        name="date.today",
        description="Get today's date in the user's preferred timezone.",
        parameters={"type": "object", "properties": {}},
        handler=_date_today,
    ),
    Tool(
        name="weather.current",
        description="Current weather and a short forecast. Use location 'auto' to detect by IP.",
        parameters={
            "type": "object",
            "properties": {
                "location": _string("City or location, e.g. 'London' or '90210'.", default="auto"),
            },
        },
        handler=_weather_current,
    ),
    Tool(
        name="news.headlines",
        description="Top tech news headlines, or search Hacker News for a query.",
        parameters={
            "type": "object",
            "properties": {
                "query": _string("Optional topic to search for, e.g. 'artificial intelligence'.")
            },
        },
        handler=_news_headlines,
    ),
    Tool(
        name="web.search",
        description="Search the web and return a few relevant page titles, URLs, and snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": _string("The search query.", minLength=1),
            },
            "required": ["query"],
        },
        handler=_web_search,
    ),
    Tool(
        name="wikipedia.summary",
        description="Get a short summary of a Wikipedia article by exact or near title.",
        parameters={
            "type": "object",
            "properties": {
                "title": _string("Wikipedia article title.", minLength=1),
            },
            "required": ["title"],
        },
        handler=_wikipedia_summary,
    ),
    Tool(
        name="dictionary.define",
        description="Get definitions and examples for an English word.",
        parameters={
            "type": "object",
            "properties": {
                "word": _string("The word to define.", minLength=1),
            },
            "required": ["word"],
        },
        handler=_dictionary_define,
    ),
    Tool(
        name="calculator.compute",
        description="Evaluate a simple arithmetic expression safely (+ - * / ^ %).",
        parameters={
            "type": "object",
            "properties": {
                "expression": _string("Arithmetic expression, e.g. '2 + 2 * 5'.", minLength=1),
            },
            "required": ["expression"],
        },
        handler=_calculator_compute,
    ),
)


def register_utility_skill(manager: ToolManager) -> None:
    for tool in _TOOLS:
        manager.register(tool)
