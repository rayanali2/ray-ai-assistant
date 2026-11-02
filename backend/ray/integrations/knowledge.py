"""Knowledge adapters for local Obsidian vaults and shared Notion pages.

An Obsidian vault is just a directory of Markdown files. This adapter walks the
configured path and reads notes without requiring an API or network call, which
fits the local-first requirement (ADR-0010).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ray.config import get_settings
from ray.integrations.base import Adapter, AdapterResult


class ObsidianAdapter(Adapter):
    """Read and search an Obsidian vault directory."""

    name = "obsidian"

    def __init__(self, vault_path: str | None = None) -> None:
        self.vault_path = vault_path

    def _vault(self) -> Path | None:
        if not self.vault_path:
            return None
        path = Path(self.vault_path).expanduser().resolve()
        if not path.is_dir():
            return None
        return path

    async def check(self) -> AdapterResult:
        path = self._vault()
        if not path:
            return AdapterResult(
                ok=False, data={}, error="Obsidian vault path is not configured or does not exist."
            )
        md_files = list(path.rglob("*.md"))
        return AdapterResult(ok=True, data={"vault": str(path), "note_count": len(md_files)})

    async def read(self, path: str = "", **kwargs: Any) -> AdapterResult:
        """Read a note by relative path, or search all notes if ``query`` is given."""
        query = kwargs.get("query")
        if query is not None:
            return await self.search(str(query))
        return await self.get_note(path)

    async def get_note(self, relative_path: str) -> AdapterResult:
        vault = self._vault()
        if not vault:
            return AdapterResult(ok=False, data={}, error="No vault configured.")
        note_path = (vault / relative_path).resolve()
        # Guard against traversal outside the vault.
        if not str(note_path).startswith(str(vault)):
            return AdapterResult(ok=False, data={}, error="Path is outside the vault.")
        if not note_path.is_file():
            return AdapterResult(ok=False, data={}, error=f"Note {relative_path!r} not found.")
        try:
            content = note_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return AdapterResult(ok=False, data={}, error=f"Could not read note: {exc}")
        return AdapterResult(
            ok=True,
            data={
                "path": relative_path,
                "name": note_path.stem,
                "content": content,
                "word_count": len(content.split()),
            },
        )

    async def search(self, query: str, *, limit: int = 10) -> AdapterResult:
        vault = self._vault()
        if not vault:
            return AdapterResult(ok=False, data={}, error="No vault configured.")
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        matches: list[dict[str, Any]] = []
        for md_file in vault.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pattern.search(content):
                rel = str(md_file.relative_to(vault))
                # Find the first matching line as a preview.
                preview = ""
                for line in content.splitlines():
                    if pattern.search(line):
                        preview = line.strip()
                        break
                matches.append({"path": rel, "name": md_file.stem, "preview": preview})
                if len(matches) >= limit:
                    break
        return AdapterResult(
            ok=True, data={"query": query, "matches": matches, "count": len(matches)}
        )


class NotionAdapter(Adapter):
    """Notion pages and databases shared with an internal integration."""

    name = "notion"

    def __init__(
        self, token: str | None = None, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.token = token or get_settings().notion_token
        self.client = client

    async def _api(self, method: str, path: str, **kwargs: Any) -> AdapterResult:
        if not self.token:
            return AdapterResult(
                False,
                {},
                "Notion is not configured. Set RAY_NOTION_TOKEN and share pages via Connections.",
            )
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": "2022-06-28"}
        try:
            for attempt in range(3):
                if self.client is not None:
                    response = await self.client.request(
                        method, "https://api.notion.com/v1" + path, headers=headers, **kwargs
                    )
                else:
                    async with httpx.AsyncClient(timeout=20) as client:
                        response = await client.request(
                            method, "https://api.notion.com/v1" + path, headers=headers, **kwargs
                        )
                if response.status_code != 429:
                    break
                delay = max(0.0, float(response.headers.get("Retry-After", "1")))
                if attempt == 2 or delay > 60:
                    return AdapterResult(
                        False, {}, f"Notion rate limited; retry after {delay:g} seconds."
                    )
                await asyncio.sleep(delay)
            if response.is_success:
                return AdapterResult(True, dict(response.json()))
            error = (
                "Notion token invalid/revoked; check RAY_NOTION_TOKEN."
                if response.status_code == 401
                else "Notion access denied/not found; share pages via Connections."
                if response.status_code in (403, 404)
                else f"Notion returned HTTP {response.status_code}."
            )
            return AdapterResult(False, {}, error)
        except (httpx.HTTPError, ValueError):
            return AdapterResult(False, {}, "Could not reach Notion or decode its response.")

    async def _pages(self, method: str, path: str, payload: dict[str, Any]) -> AdapterResult:
        items: list[dict[str, Any]] = []
        while True:
            kwargs = {"json" if method == "POST" else "params": payload}
            result = await self._api(method, path, **kwargs)
            if not result.ok:
                return result
            items.extend(result.data.get("results", []))
            if not result.data.get("has_more"):
                return AdapterResult(True, {"results": items})
            cursor = result.data.get("next_cursor")
            if not cursor or cursor == payload.get("start_cursor"):
                return AdapterResult(False, {}, "Notion returned an invalid pagination cursor.")
            payload = {**payload, "start_cursor": cursor}

    async def check(self) -> AdapterResult:
        result = await self._api("GET", "/users/me")
        return AdapterResult(result.ok, {}, result.error)

    async def read(self, path: str = "", **kwargs: Any) -> AdapterResult:
        return await self.read_page(path)

    async def search(self, query: str = "", object_type: str = "") -> AdapterResult:
        payload: dict[str, Any] = {"query": query, "page_size": 100}
        if object_type:
            payload["filter"] = {"value": object_type, "property": "object"}
        return await self._pages("POST", "/search", payload)

    async def read_page(self, page_id: str) -> AdapterResult:
        async def render(block_id: str, depth: int = 0) -> AdapterResult:
            if depth > 20:
                return AdapterResult(False, {}, "Notion block nesting is too deep.")
            result = await self._pages(
                "GET", f"/blocks/{quote(block_id, safe='')}/children", {"page_size": 100}
            )
            if not result.ok:
                return result
            lines: list[str] = []
            for block in result.data["results"]:
                kind = block.get("type", "")
                value = block.get(kind, {})
                text = "".join(
                    item.get("plain_text", item.get("text", {}).get("content", ""))
                    for item in value.get("rich_text", [])
                )
                prefix = {
                    "heading_1": "# ",
                    "heading_2": "## ",
                    "heading_3": "### ",
                    "bulleted_list_item": "- ",
                    "numbered_list_item": "1. ",
                    "quote": "> ",
                    "to_do": "- [x] " if value.get("checked") else "- [ ] ",
                }.get(kind, "")
                if kind == "code":
                    text = f"```{value.get('language', '')}\n{text}\n```"
                lines.append(prefix + text)
                if block.get("has_children"):
                    children = await render(block["id"], depth + 1)
                    if not children.ok:
                        return children
                    lines.append(children.data["content"])
            return AdapterResult(True, {"content": "\n".join(lines)})

        return await render(page_id)

    @staticmethod
    def _blocks(content: str) -> list[dict[str, Any]]:
        return [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content[i : i + 2000]}}]
                },
            }
            for i in range(0, len(content), 2000)
        ]

    async def create_page(
        self,
        parent_id: str,
        title: str,
        content: str = "",
        parent_type: str = "page_id",
        title_property: str = "Name",
    ) -> AdapterResult:
        blocks = self._blocks(content)
        result = await self._api(
            "POST",
            "/pages",
            json={
                "parent": {parent_type: parent_id},
                "properties": {
                    "title" if parent_type == "page_id" else title_property: {
                        "type": "title",
                        "title": [{"type": "text", "text": {"content": title}}],
                    }
                },
                "children": blocks[:100],
            },
        )
        if result.ok and len(blocks) > 100:
            appended = await self._append(result.data["id"], blocks[100:])
            if not appended.ok:
                return AdapterResult(
                    False,
                    {"page_id": result.data["id"]},
                    f"Page {result.data['id']} was created, but remaining content failed: "
                    f"{appended.error} Do not create it again.",
                )
        return result

    async def _append(self, page_id: str, blocks: list[dict[str, Any]]) -> AdapterResult:
        result = AdapterResult(True, {})
        for index in range(0, len(blocks), 100):
            result = await self._api(
                "PATCH",
                f"/blocks/{quote(page_id, safe='')}/children",
                json={"children": blocks[index : index + 100]},
            )
            if not result.ok:
                return AdapterResult(
                    False,
                    {"page_id": page_id, "appended_blocks": index},
                    f"Append to {page_id} stopped after {index} blocks: {result.error} "
                    "Check existing content before retrying.",
                )
        return result

    async def append_page(self, page_id: str, content: str) -> AdapterResult:
        return await self._append(page_id, self._blocks(content))
