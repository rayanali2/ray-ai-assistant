"""Free, no-key adapters for everyday reference data.

These deliberately avoid API keys: weather uses wttr.in, news uses the Hacker News
public search API, wikipedia uses the official REST summary endpoint, and the dictionary
uses dictionaryapi.dev.  Real-time web search is the only non-trivial one: DuckDuckGo's
HTML frontend is scraped lightly because it has no public JSON API.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import httpx

from ray.integrations.base import AdapterResult


def _client() -> httpx.AsyncClient:
    # Short timeout: these are best-effort lookups, not the main model call.
    return httpx.AsyncClient(timeout=15.0, follow_redirects=True)


async def weather_current(location: str) -> AdapterResult:
    """Current conditions and a short forecast from wttr.in."""
    safe = location.strip() or "auto"
    try:
        async with _client() as client:
            response = await client.get(f"https://wttr.in/{urllib.parse.quote(safe)}?format=j1")
        response.raise_for_status()
        data = response.json()
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        forecast = data.get("weather", [])[:3]
        return AdapterResult(
            ok=True,
            data={
                "location": f"{area.get('areaName', [{}])[0].get('value', safe)}, "
                f"{area.get('country', [{}])[0].get('value', '')}".strip(", "),
                "temperature_c": current.get("temp_C"),
                "temperature_f": current.get("temp_F"),
                "condition": current.get("weatherDesc", [{}])[0].get("value"),
                "humidity": current.get("humidity"),
                "wind": f"{current.get('windspeedKmph', '')} km/h",
                "forecast": [
                    {"date": w.get("date"), "max_c": w.get("maxtempC"), "min_c": w.get("mintempC")}
                    for w in forecast
                ],
            },
        )
    except httpx.HTTPStatusError as exc:
        return AdapterResult(
            ok=False, data={}, error=f"Weather service returned {exc.response.status_code}."
        )
    except (httpx.HTTPError, json.JSONDecodeError, IndexError) as exc:
        return AdapterResult(ok=False, data={}, error=f"Could not reach weather service: {exc}")


async def news_headlines(query: str | None = None) -> AdapterResult:
    """Top Hacker News stories, or search them if a query is supplied."""
    try:
        async with _client() as client:
            if query:
                url = (
                    "https://hn.algolia.com/api/v1/search"
                    f"?query={urllib.parse.quote(query)}&hitsPerPage=5"
                )
            else:
                url = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=5"
            response = await client.get(url)
        response.raise_for_status()
        hits = response.json().get("hits", [])
        return AdapterResult(
            ok=True,
            data={
                "stories": [
                    {
                        "title": h.get("title") or h.get("story_title"),
                        "url": h.get("url"),
                        "points": h.get("points"),
                        "author": h.get("author"),
                    }
                    for h in hits[:5]
                    if h.get("title") or h.get("story_title")
                ]
            },
        )
    except httpx.HTTPStatusError as exc:
        return AdapterResult(
            ok=False, data={}, error=f"News service returned {exc.response.status_code}."
        )
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return AdapterResult(ok=False, data={}, error=f"Could not reach news service: {exc}")


async def web_search(query: str) -> AdapterResult:
    """A lightweight DuckDuckGo HTML scrape.  Returns a few title/URL/snippet triples."""
    try:
        async with _client() as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "en-us"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; RayBot/1.0)"},
            )
        response.raise_for_status()
        text = response.text
        results: list[dict[str, str]] = []
        # Each result block contains a link with class result__a and a snippet with
        # class result__snippet.
        for link_match, snippet_match in zip(
            re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text),
            re.finditer(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text),
            strict=False,
        ):
            href = link_match.group(1)
            title = re.sub(r"<[^>]+>", "", link_match.group(2))
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
            # DuckDuckGo links are redirects with the real URL in a uddg parameter.
            real_url = href
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                real_url = urllib.parse.unquote(parsed.get("uddg", [href])[0])
            results.append({"title": title.strip(), "url": real_url, "snippet": snippet.strip()})
            if len(results) >= 5:
                break
        if not results:
            return AdapterResult(ok=False, data={}, error="No web search results found.")
        return AdapterResult(ok=True, data={"results": results, "query": query})
    except httpx.HTTPStatusError as exc:
        return AdapterResult(
            ok=False, data={}, error=f"Search service returned {exc.response.status_code}."
        )
    except httpx.HTTPError as exc:
        return AdapterResult(ok=False, data={}, error=f"Could not reach search service: {exc}")


async def wikipedia_summary(title: str) -> AdapterResult:
    """A short summary of a Wikipedia page by title."""
    try:
        async with _client() as client:
            response = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
            )
        if response.status_code == 404:
            return AdapterResult(ok=False, data={}, error=f"Wikipedia has no page for '{title}'.")
        response.raise_for_status()
        data = response.json()
        return AdapterResult(
            ok=True,
            data={
                "title": data.get("title"),
                "description": data.get("description"),
                "extract": data.get("extract"),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
            },
        )
    except httpx.HTTPStatusError as exc:
        return AdapterResult(
            ok=False, data={}, error=f"Wikipedia returned {exc.response.status_code}."
        )
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return AdapterResult(ok=False, data={}, error=f"Could not reach Wikipedia: {exc}")


async def dictionary_define(word: str) -> AdapterResult:
    """Definitions and examples for an English word."""
    try:
        async with _client() as client:
            response = await client.get(
                f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
            )
        if response.status_code == 404:
            return AdapterResult(ok=False, data={}, error=f"No dictionary entry for '{word}'.")
        response.raise_for_status()
        entries = response.json()
        meanings: list[dict[str, Any]] = []
        for entry in entries[:1]:
            for meaning in entry.get("meanings", [])[:3]:
                defs = [
                    {"definition": d.get("definition"), "example": d.get("example")}
                    for d in meaning.get("definitions", [])[:3]
                ]
                meanings.append(
                    {"part_of_speech": meaning.get("partOfSpeech"), "definitions": defs}
                )
        return AdapterResult(ok=True, data={"word": word, "meanings": meanings})
    except httpx.HTTPStatusError as exc:
        return AdapterResult(
            ok=False, data={}, error=f"Dictionary returned {exc.response.status_code}."
        )
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return AdapterResult(ok=False, data={}, error=f"Could not reach dictionary: {exc}")
