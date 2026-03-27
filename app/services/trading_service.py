"""Trading orchestration for live and paper execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.config.settings import Settings
from app.models.interfaces import AbstractExecutionProvider
from app.models.trading import (
    AccountSummary,
    ClosePositionRequest,
    ClosePositionResponse,
    MarketOrderRequest,
    MarketOrderResponse,
    PositionSummary,
    TradeMode,
    TradeRecord,
)
from app.persistence.supabase import SupabasePersistence
from app.services.market_data_service import MarketDataService
from app.services.signal_service import SignalService


class TradingService:
    """Validate, risk-check, execute, and persist trading actions."""

    def __init__(
        self,
        settings: Settings,
        signal_service: SignalService,
        market_data_service: MarketDataService,
        persistence: Optional[SupabasePersistence],
        broker: Optional[AbstractExecutionProvider],
    ):
        self._settings = settings
        self._signal_service = signal_service
        self._market_data_service = market_data_service
        self._persistence = persistence
        self._broker = broker

    async def get_account_summary(self) -> AccountSummary:
        """Return the broker account summary."""

        broker = self._require_broker()
        return await broker.get_account_summary()

    async def list_open_positions(self) -> List[PositionSummary]:
        """Return the current broker positions."""

        broker = self._require_broker()
        return await broker.list_open_positions()

    async def list_recent_trades(self, limit: int = 20) -> List[TradeRecord]:
        """Return recent persisted trade records."""

        if self._persistence is None:
            return []
        return await self._persistence.list_recent_trades(limit=limit)

    async def place_market_order(self, request: MarketOrderRequest) -> MarketOrderResponse:
        """Validate risk constraints and execute a market order."""

        request = request.copy(update={"pair": self._signal_service.resolve_pair(request.pair)})
        if request.units > self._settings.max_order_units:
            raise ValueError(
                f"Order size exceeds MAX_ORDER_UNITS={self._settings.max_order_units}."
            )

        if self._settings.trade_mode == TradeMode.LIVE.value:
            if self._settings.execution_provider == "oanda":
                account = await self.get_account_summary()
                await self._enforce_live_risk_limits(account)
                positions = await self.list_open_positions()
                open_sides = sum(
                    int(position.long.units > 0) + int(abs(position.short.units) > 0)
                    for position in positions
                )
                if open_sides >= self._settings.max_open_positions:
                    raise RuntimeError(
                        f"Max open positions reached ({self._settings.max_open_positions})."
                    )

            response = await self._require_broker().place_market_order(request)
        else:
            snapshot, _recent_ticks = await self._market_data_service.get_market_context(
                request.pair,
                lookback_seconds=self._settings.lookback_seconds,
            )
            fill_price = snapshot.ask if request.side.value == "BUY" else snapshot.bid
            response = MarketOrderResponse(
                mode=TradeMode.PAPER,
                pair=request.pair,
                display_pair=self._signal_service.display_pair(request.pair),
                side=request.side,
                units=request.units,
                status="simulated",
                fill_price=fill_price,
                requested_price=snapshot.mid_price,
                account_id=self._settings.oanda_account_id,
                message="Paper order simulated from current market snapshot.",
                timestamp=datetime.now(timezone.utc),
            )

        await self._record_trade(
            TradeRecord(
                id=str(uuid4()),
                mode=response.mode,
                pair=response.pair,
                side=response.side,
                action="open",
                units=str(response.units),
                status=response.status,
                fill_price=response.fill_price,
                realized_pnl=None,
                external_order_id=response.external_order_id,
                external_trade_id=response.external_trade_id,
                account_id=response.account_id,
                request_source=request.request_source,
                requested_by=request.requested_by,
                error_message=None,
                request_payload=request.dict(),
                response_payload=response.dict(),
                created_at=response.timestamp,
                closed_at=None,
            )
        )
        return response

    async def close_position(
        self,
        pair: str,
        request: ClosePositionRequest,
        request_source: str,
        requested_by: Optional[str] = None,
    ) -> ClosePositionResponse:
        """Close an open position."""

        normalized_pair = self._signal_service.resolve_pair(pair)
        if self._settings.trade_mode != TradeMode.LIVE.value:
            raise RuntimeError("Position closeout requires TRADE_MODE=live.")

        response = await self._require_broker().close_position(normalized_pair, request)
        await self._record_trade(
            TradeRecord(
                id=str(uuid4()),
                mode=response.mode,
                pair=response.pair,
                side=None,
                action="close",
                units=response.units,
                status=response.status,
                fill_price=None,
                realized_pnl=response.realized_pnl,
                external_order_id=response.external_order_id,
                external_trade_id=None,
                account_id=self._settings.oanda_account_id,
                request_source=request_source,
                requested_by=requested_by,
                error_message=None,
                request_payload=request.dict(),
                response_payload=response.dict(),
                created_at=response.timestamp,
                closed_at=response.timestamp,
            )
        )
        return response

    async def _enforce_live_risk_limits(self, account: AccountSummary) -> None:
        """Block live trading when basic risk guardrails are violated."""

        if account.margin_available <= 0:
            raise RuntimeError("Insufficient margin available.")

        if (
            account.margin_closeout_percent is not None
            and account.margin_closeout_percent >= self._settings.max_margin_closeout_percent
        ):
            raise RuntimeError("Margin closeout threshold exceeded.")

        if self._persistence is None:
            return
        daily_realized_pnl = await self._persistence.get_daily_realized_pnl(TradeMode.LIVE)
        allowed_loss = account.nav * (self._settings.max_daily_loss_percent / 100.0)
        if daily_realized_pnl <= -allowed_loss:
            raise RuntimeError(
                f"Daily realized loss limit exceeded ({daily_realized_pnl:.2f})."
            )

    async def _record_trade(self, record: TradeRecord) -> None:
        if self._persistence is None:
            return
        await self._persistence.record_trade(record)

    def _require_broker(self) -> AbstractExecutionProvider:
        if self._broker is None:
            raise RuntimeError("Live execution provider is not configured.")
        return self._broker
