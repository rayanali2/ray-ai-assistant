"""Health check — the only unauthenticated route (ADR-0006).

The response includes a compact diagnostics map so the dashboard and CLI can show
self-diagnosis without needing an authenticated /system/diagnostics call.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ray.config import Settings, get_settings
from ray.db.session import get_session
from ray.llm.registry import get_registry
from ray.schemas import HealthResponse, VoiceCapabilities
from ray.services import integration_service, user_service
from ray.version import __version__
from ray.voice.manager import VoiceManager

router = APIRouter(tags=["health"])


def _llm_status() -> str:
    if get_registry().active_provider:
        return get_registry().active_provider or "unconfigured"
    for info in get_registry().describe():
        if info.configured:
            return info.name
    return "unconfigured"


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    # A health check that does not touch the database tells you nothing useful.
    try:
        await session.execute(text("SELECT 1"))
        database = "connected"
    except Exception:
        database = "unavailable"

    caps = VoiceManager(settings).info()

    llm_status = _llm_status()
    diagnostics: dict[str, str] = {
        "database": database,
        "llm": llm_status,
        "voice": f"local ({caps.stt_backend} / {caps.tts_backend})"
        if caps.local_ready
        else "browser fallback",
    }

    first_user = await user_service.get_first_user(session)
    if first_user is not None:
        integrations = await integration_service.list_integrations(session, first_user.id)
        failed = [i for i in integrations if i.status.value == "error"]
        diagnostics["integrations"] = f"{len(integrations)} configured" + (
            f", {len(failed)} error" if failed else ""
        )

    if database != "connected":
        diagnostics["suggestion"] = "Check DATABASE_URL and that Postgres is running."
    elif llm_status in {"unconfigured", "mock"}:
        diagnostics["suggestion"] = (
            "No model configured — add a Gemini key in desktop Preferences or run Ollama."
        )

    return HealthResponse(
        status="ok" if database == "connected" else "degraded",
        version=__version__,
        database=database,
        llm_provider=llm_status,
        diagnostics=diagnostics,
        voice=VoiceCapabilities(
            stt_backend=caps.stt_backend,
            tts_backend=caps.tts_backend,
            wake_word_enabled=caps.wake_word_enabled,
            wake_words=caps.wake_words,
            local_ready=caps.local_ready,
            local_detail=caps.local_detail,
        ),
    )
