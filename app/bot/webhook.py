"""Webhook integration for running python-telegram-bot inside FastAPI."""

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from telegram import Update
from telegram.ext import Application

from app.bootstrap import AppContext
from app.bot.handlers import build_telegram_application, restore_watch_jobs

logger = logging.getLogger(__name__)

router = APIRouter()


async def start_telegram_application(app_context: AppContext) -> Optional[Application]:
    """Initialize and start the Telegram application for webhook processing."""

    settings = app_context.settings
    if not settings.telegram_bot_token:
        logger.info("Telegram bot token not configured; webhook startup skipped.")
        return None

    application = build_telegram_application(app_context)
    await application.initialize()
    await application.start()
    await restore_watch_jobs(application, app_context)

    if settings.telegram_webhook_url:
        webhook_kwargs = {"url": settings.telegram_webhook_url}
        if settings.telegram_webhook_secret:
            webhook_kwargs["secret_token"] = settings.telegram_webhook_secret
        await application.bot.set_webhook(**webhook_kwargs)
        logger.info("Telegram webhook registered: %s", settings.telegram_webhook_url)
    else:
        logger.info("TELEGRAM_WEBHOOK_URL not set; webhook registration skipped.")

    return application


async def stop_telegram_application(application: Optional[Application]) -> None:
    """Stop and shut down the Telegram application."""

    if application is None:
        return

    await application.stop()
    await application.shutdown()


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> Response:
    """Accept Telegram webhook updates and enqueue them for PTB processing."""

    application = getattr(request.app.state, "telegram_application", None)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured.",
        )

    expected_secret = request.app.state.app_context.settings.telegram_webhook_secret
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram webhook secret.",
        )

    update = Update.de_json(await request.json(), application.bot)
    await application.update_queue.put(update)
    return Response(status_code=status.HTTP_200_OK)
