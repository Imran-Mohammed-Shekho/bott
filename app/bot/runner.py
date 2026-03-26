"""CLI entry point for serving the webhook-based Telegram bot."""

import uvicorn

from app.config.settings import get_settings


def main() -> None:
    """Start the FastAPI app that receives Telegram webhook updates."""

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
