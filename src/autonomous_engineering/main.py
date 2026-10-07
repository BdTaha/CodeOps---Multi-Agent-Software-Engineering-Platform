"""Application factory and dependency composition root."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from autonomous_engineering.api.health import router as health_router
from autonomous_engineering.core.config import Settings
from autonomous_engineering.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independent app; injected settings keep tests deterministic."""
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        logger.info("Service starting environment=%s", config.environment)
        try:
            yield
        finally:
            logger.info("Service stopping")

    app = FastAPI(title=config.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.include_router(health_router)
    return app
