"""Basic API tests for the FastAPI application."""

import os

from fastapi.testclient import TestClient

os.environ["MARKET_DATA_PROVIDER"] = "mock"
os.environ["PREDICTION_PROVIDER"] = "mock"

from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    """Health endpoint should respond successfully."""

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["supported_pairs"] >= 1
    assert payload["market_data_provider"] in {"mock", "oanda"}
    assert payload["prediction_provider"] in {"mock", "sklearn"}


def test_signal_endpoint_returns_expected_shape() -> None:
    """Signal endpoint should include pair, signals, and disclaimer."""

    response = client.get("/api/v1/signal/EURUSD")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pair"] == "EURUSD"
    assert payload["display_pair"] == "EUR/USD"
    assert set(payload["signals"].keys()) == {"5s", "10s", "30s", "1m"}
    assert "disclaimer" in payload
