"""Webhook integration tests."""

import os

from fastapi.testclient import TestClient

os.environ["MARKET_DATA_PROVIDER"] = "mock"
os.environ["PREDICTION_PROVIDER"] = "mock"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app.main import app


client = TestClient(app)


def test_telegram_webhook_returns_503_without_bot_configuration() -> None:
    """Webhook endpoint should be unavailable when Telegram is not configured."""

    response = client.post("/telegram/webhook", json={"update_id": 1})
    assert response.status_code == 503
