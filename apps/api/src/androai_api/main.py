import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.v1.router import router as v1_router
from .config import get_settings
from .errors import register_error_handlers

log = logging.getLogger("androai_api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Validates all required configuration; raises (aborting startup) if invalid.
    settings = get_settings()
    log.info("Starting %s (%s)", settings.app_name, settings.environment)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AndroAI API", version=__version__, lifespan=lifespan)
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[get_settings().app_url],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict:
        """Liveness: process is up. Does not touch dependencies."""
        s = get_settings()
        return {
            "status": "ok",
            "service": s.app_name,
            "version": __version__,
            "environment": s.environment,
            "time": datetime.now(timezone.utc).isoformat(),
        }

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
