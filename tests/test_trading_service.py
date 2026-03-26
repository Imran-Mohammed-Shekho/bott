"""Unit tests for the trading orchestration layer."""

import asyncio
import os

from app.bootstrap import build_app_context
from app.config.settings import get_settings
from app.models.trading import MarketOrderRequest, OrderSide


os.environ["MARKET_DATA_PROVIDER"] = "mock"
os.environ["PREDICTION_PROVIDER"] = "mock"
os.environ["TRADE_MODE"] = "paper"
get_settings.cache_clear()


def test_paper_market_order_returns_simulated_fill() -> None:
    """Paper mode should simulate fills without a broker."""

    app_context = build_app_context()
    response = asyncio.run(
        app_context.trading_service.place_market_order(
            MarketOrderRequest(pair="EURUSD", side=OrderSide.BUY, units=100)
        )
    )

    assert response.mode.value == "paper"
    assert response.status == "simulated"
    assert response.fill_price is not None


def test_market_order_rejects_oversized_units() -> None:
    """Orders above the configured cap should fail fast."""

    app_context = build_app_context()
    try:
        asyncio.run(
            app_context.trading_service.place_market_order(
                MarketOrderRequest(pair="EURUSD", side=OrderSide.BUY, units=1000000)
            )
        )
    except ValueError as exc:
        assert "MAX_ORDER_UNITS" in str(exc)
    else:
        raise AssertionError("Expected oversized order to fail.")
