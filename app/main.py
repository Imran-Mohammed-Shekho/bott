"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.bot.webhook import (
    router as telegram_router,
    start_telegram_application,
    stop_telegram_application,
)
from app.bootstrap import build_app_context
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the FastAPI application."""

    settings = get_settings()
    app_context = build_app_context()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Attach the shared application context and manage Telegram webhook lifecycle."""

        app.state.app_context = app_context
        if app_context.persistence is not None:
            await app_context.persistence.initialize()
        app.state.telegram_application = await start_telegram_application(app_context)
        logger.info(
            "Starting API with %d supported pairs",
            len(app_context.settings.available_pairs),
        )
        yield
        await stop_telegram_application(app.state.telegram_application)
        if app_context.persistence is not None:
            await app_context.persistence.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Forex trading signals API with mock predictions and Telegram integration.",
        lifespan=lifespan,
    )
    app.state.app_context = app_context
    app.include_router(router, prefix="/api/v1", tags=["signals"])
    app.include_router(telegram_router, tags=["telegram"])

    @app.get("/")
    async def root() -> dict:
        """Return a small root payload for convenience."""

        return {
            "message": "Forex Signals Bot API",
            "docs": "/docs",
            "telegram_webhook_path": "/telegram/webhook",
        }

    return app


app = create_app()


if __name__ == "__main__":
    settings = build_app_context().settings
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
