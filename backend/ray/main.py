"""Ray's FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ray.api.routes import (
    agents,
    approvals,
    calendar,
    chat,
    dashboard,
    health,
    integrations,
    memory,
    projects,
    system,
    tasks,
    tools,
    user,
    voice,
    workflows,
)
from ray.config import get_settings
from ray.core.scheduler import start_scheduler, stop_scheduler
from ray.db.session import dispose_engine
from ray.llm.registry import dispose_registry, get_registry
from ray.logging_config import configure_logging
from ray.security.auth import verify_token

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(json=not settings.is_development)
    # Log the resolved chain, not just the preference: "gemini" in the config and
    # no key set is a very different runtime state.
    chain = [
        f"{info.name}{'' if info.configured else ' (unconfigured)'}"
        for info in get_registry().describe()
    ]
    log.info("ray.startup", env=settings.env, llm_chain=chain)
    start_scheduler()
    yield
    await stop_scheduler()
    await dispose_registry()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Ray API",
        version="0.1.0",
        description="Personal AI assistant backend.",
        lifespan=lifespan,
        # Hide the interactive docs outside development: Ray is a personal service,
        # not a public API.
        docs_url="/docs" if settings.is_development else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    # Everything else is authenticated. Applying the dependency here rather than
    # per-route means a new router cannot accidentally ship unprotected
    # (ADR-0006).
    protected = [Depends(verify_token)]
    app.include_router(user.router, dependencies=protected)
    app.include_router(dashboard.router, dependencies=protected)
    app.include_router(projects.router, dependencies=protected)
    app.include_router(tasks.router, dependencies=protected)
    app.include_router(agents.router, dependencies=protected)
    app.include_router(chat.router, dependencies=protected)
    app.include_router(memory.router, dependencies=protected)
    app.include_router(tools.router, dependencies=protected)
    app.include_router(approvals.router, dependencies=protected)
    app.include_router(calendar.router, dependencies=protected)
    app.include_router(integrations.router, dependencies=protected)
    app.include_router(system.router, dependencies=protected)
    app.include_router(workflows.router, dependencies=protected)
    # Voice has its own query-param auth because WebSocket browsers cannot set
    # arbitrary headers. It still verifies the API token before accepting.
    app.include_router(voice.router)

    return app


app = create_app()
