"""Built-in system skill: local computer state and basic actions."""

from __future__ import annotations

import asyncio
import platform
import shutil
import webbrowser
from datetime import UTC, datetime

from ray.services.errors import ServiceError
from ray.tools.manager import Tool, ToolContext, ToolManager


def _string(description: str, **extra: object) -> dict[str, object]:
    return {"type": "string", "description": description, **extra}


async def _system_info(ctx: ToolContext, _arguments: dict[str, object]) -> dict[str, object]:
    """Read-only local system information."""
    data: dict[str, object] = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python_version": platform.python_version(),
        "cpu_count": __import__("os").cpu_count(),
    }
    try:
        disk = shutil.disk_usage("/")
        data["disk_free_gb"] = round(disk.free / (1024**3), 2)
        data["disk_total_gb"] = round(disk.total / (1024**3), 2)
    except OSError:
        data["disk_free_gb"] = None
        data["disk_total_gb"] = None
    try:
        # Linux / macOS load average.
        data["load_average"] = list(__import__("os").getloadavg())
    except (AttributeError, OSError):
        data["load_average"] = None
    data["utc_now"] = datetime.now(UTC).isoformat()
    return {"ok": True, **data}


async def _system_open_url(ctx: ToolContext, arguments: dict[str, object]) -> dict[str, object]:
    url = str(arguments.get("url", "")).strip()
    if not url:
        raise ServiceError("url is required.")
    if not url.startswith(("http://", "https://")):
        raise ServiceError("Only http:// or https:// URLs are allowed.")

    # webbrowser.open is sync and may fail headless; use it if it works, otherwise
    # launch the platform handler asynchronously.
    try:
        if webbrowser.open(url):
            return {"ok": True, "opened": url}
    except Exception:
        pass

    system = platform.system()
    if system == "Darwin":
        cmd = ["open", url]
    elif system == "Linux":
        cmd = ["xdg-open", url]
    elif system == "Windows":
        cmd = ["cmd", "/c", "start", url]
    else:
        raise ServiceError("Could not open the URL on this platform.")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.wait(), timeout=2.0)
    return {"ok": True, "opened": url}


_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="system.info",
        description="Read basic information about the local machine (OS, CPU, disk, load).",
        parameters={"type": "object", "properties": {}},
        handler=_system_info,
    ),
    Tool(
        name="system.open_url",
        description="Open a URL in the default browser. Always asks for approval first.",
        parameters={
            "type": "object",
            "properties": {"url": _string("The http:// or https:// URL to open.", minLength=1)},
            "required": ["url"],
        },
        handler=_system_open_url,
        side_effect=True,
        summarise=lambda args: f"Open {args.get('url', '')} in the browser",
    ),
)


def register_system_skill(manager: ToolManager) -> None:
    for tool in _TOOLS:
        manager.register(tool)
