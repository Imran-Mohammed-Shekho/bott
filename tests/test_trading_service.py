"""Unit tests for the trading orchestration layer."""

import asyncio
import os
from datetime import datetime, timezone

from app.bootstrap import build_app_context
from app.config.settings import get_settings
from app.models.interfaces import AbstractExecutionProvider
from app.models.trading import MarketOrderRequest, OrderSide
from app.models.trading import AccountSummary, ClosePositionRequest, ClosePositionResponse, MarketOrderResponse, PositionSummary, TradeMode
from app.services.trading_service import TradingService


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


class _FakeExecutionProvider(AbstractExecutionProvider):
    async def get_account_summary(self) -> AccountSummary:
        raise AssertionError("Should not be called for pocket_option_browser execution.")

    async def list_open_positions(self) -> list[PositionSummary]:
        raise AssertionError("Should not be called for pocket_option_browser execution.")

    async def place_market_order(self, request: MarketOrderRequest) -> MarketOrderResponse:
        return MarketOrderResponse(
            mode=TradeMode.LIVE,
            pair=request.pair,
            display_pair="EUR/USD",
            side=request.side,
            units=request.units,
            status="submitted",
            fill_price=None,
            requested_price=None,
            external_order_id=None,
            external_trade_id=None,
            account_id="pocket_option_browser",
            message="submitted",
            timestamp=datetime.now(timezone.utc),
        )

    async def close_position(
        self,
        pair: str,
        request: ClosePositionRequest,
    ) -> ClosePositionResponse:
        raise AssertionError("Should not be called in this test.")


def test_live_pocket_option_execution_bypasses_oanda_account_checks() -> None:
    """Pocket Option browser execution should not require OANDA account endpoints."""

    os.environ["TRADE_MODE"] = "live"
    os.environ["EXECUTION_PROVIDER"] = "pocket_option_browser"
    get_settings.cache_clear()
    app_context = build_app_context()
    service = TradingService(
        settings=app_context.settings,
        signal_service=app_context.signal_service,
        market_data_service=app_context.market_data_service,
        persistence=None,
        broker=_FakeExecutionProvider(),
    )

    response = asyncio.run(
        service.place_market_order(
            MarketOrderRequest(pair="EURUSD", side=OrderSide.BUY, units=1)
        )
    )

    assert response.mode.value == "live"
    assert response.status == "submitted"

    os.environ["TRADE_MODE"] = "paper"
    os.environ["EXECUTION_PROVIDER"] = "oanda"
    get_settings.cache_clear()
