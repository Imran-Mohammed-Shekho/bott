"""OANDA-backed order execution provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config.settings import Settings
from app.models.interfaces import AbstractExecutionProvider
from app.models.trading import (
    AccountSummary,
    ClosePositionRequest,
    ClosePositionResponse,
    MarketOrderRequest,
    MarketOrderResponse,
    OrderSide,
    PositionCloseSide,
    PositionExposure,
    PositionSummary,
    TradeMode,
)
from app.services.signal_service import SignalService


class OandaTradingProvider(AbstractExecutionProvider):
    """Execute market orders and read account state from OANDA."""

    def __init__(self, settings: Settings):
        self._settings = settings
        if not settings.oanda_api_token or not settings.oanda_account_id:
            raise ValueError(
                "OANDA_API_TOKEN and OANDA_ACCOUNT_ID are required for OANDA trading."
            )

    async def get_account_summary(self) -> AccountSummary:
        """Return the account summary from OANDA."""

        payload = await self._get_json(
            path=f"/accounts/{self._settings.oanda_account_id}/summary",
        )
        account = payload["account"]
        return AccountSummary(
            account_id=account["id"],
            currency=account["currency"],
            balance=float(account["balance"]),
            nav=float(account["NAV"]),
            unrealized_pnl=float(account["unrealizedPL"]),
            margin_available=float(account["marginAvailable"]),
            margin_used=float(account["marginUsed"]),
            open_trade_count=int(account["openTradeCount"]),
            open_position_count=int(account["openPositionCount"]),
            pending_order_count=int(account["pendingOrderCount"]),
            margin_closeout_percent=float(account.get("marginCloseoutPercent") or 0.0),
        )

    async def list_open_positions(self) -> List[PositionSummary]:
        """Return open positions from OANDA."""

        payload = await self._get_json(
            path=f"/accounts/{self._settings.oanda_account_id}/openPositions",
        )
        positions = payload.get("positions", [])
        records: List[PositionSummary] = []
        for position in positions:
            pair = self._normalize_instrument(position["instrument"])
            records.append(
                PositionSummary(
                    pair=pair,
                    display_pair=SignalService.display_pair(pair),
                    long=self._exposure_from_payload(position.get("long", {})),
                    short=self._exposure_from_payload(position.get("short", {})),
                    margin_used=float(position.get("marginUsed") or 0.0),
                )
            )
        return records

    async def place_market_order(self, request: MarketOrderRequest) -> MarketOrderResponse:
        """Create a market order."""

        payload = {
            "order": {
                "type": "MARKET",
                "instrument": self._instrument_name(request.pair),
                "units": str(request.units if request.side == OrderSide.BUY else -request.units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        if request.take_profit_price:
            payload["order"]["takeProfitOnFill"] = {"price": self._format_price(request.take_profit_price)}
        if request.stop_loss_price:
            payload["order"]["stopLossOnFill"] = {"price": self._format_price(request.stop_loss_price)}

        response = await self._request_json(
            method="POST",
            path=f"/accounts/{self._settings.oanda_account_id}/orders",
            json=payload,
        )

        fill = response.get("orderFillTransaction", {})
        trades_opened = fill.get("tradesOpened") or []
        external_trade_id = trades_opened[0]["tradeID"] if trades_opened else None
        create_transaction = response.get("orderCreateTransaction", {})
        return MarketOrderResponse(
            mode=TradeMode.LIVE,
            pair=request.pair,
            display_pair=SignalService.display_pair(request.pair),
            side=request.side,
            units=request.units,
            status="filled",
            fill_price=float(fill["price"]) if fill.get("price") else None,
            external_order_id=str(create_transaction.get("id")) if create_transaction.get("id") else None,
            external_trade_id=external_trade_id,
            account_id=self._settings.oanda_account_id,
            message="Order filled by OANDA.",
            timestamp=self._parse_timestamp(fill.get("time")),
        )

    async def close_position(
        self,
        pair: str,
        request: ClosePositionRequest,
    ) -> ClosePositionResponse:
        """Close an open position on OANDA."""

        payload: Dict[str, str] = {}
        close_units = "ALL" if request.units is None else str(request.units)

        if request.side == PositionCloseSide.ALL:
            payload["longUnits"] = "ALL"
            payload["shortUnits"] = "ALL"
        elif request.side == PositionCloseSide.LONG:
            payload["longUnits"] = close_units
        else:
            payload["shortUnits"] = close_units

        response = await self._request_json(
            method="PUT",
            path=f"/accounts/{self._settings.oanda_account_id}/positions/{self._instrument_name(pair)}/close",
            json=payload,
        )

        fill = (
            response.get("longOrderFillTransaction")
            or response.get("shortOrderFillTransaction")
            or {}
        )
        create_transaction = (
            response.get("longOrderCreateTransaction")
            or response.get("shortOrderCreateTransaction")
            or {}
        )
        return ClosePositionResponse(
            mode=TradeMode.LIVE,
            pair=pair,
            display_pair=SignalService.display_pair(pair),
            closed_side=request.side,
            units=close_units,
            status="closed",
            external_order_id=str(create_transaction.get("id")) if create_transaction.get("id") else None,
            realized_pnl=float(fill["pl"]) if fill.get("pl") else None,
            message="Position closeout submitted to OANDA.",
            timestamp=self._parse_timestamp(fill.get("time")),
        )

    async def _get_json(self, path: str) -> Dict[str, Any]:
        """Perform a GET request against OANDA's REST API."""

        return await self._request_json(method="GET", path=path, json=None)

    async def _request_json(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Perform an authenticated OANDA API request."""

        base_url = self._settings.oanda_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self._settings.oanda_api_token}",
            "Accept-Datetime-Format": "RFC3339",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._settings.market_data_timeout_seconds) as client:
            response = await client.request(
                method=method,
                url=f"{base_url}{path}",
                headers=headers,
                json=json,
            )

        response.raise_for_status()
        payload = response.json()
        if payload.get("errorMessage"):
            raise RuntimeError(str(payload["errorMessage"]))
        return payload

    @staticmethod
    def _instrument_name(pair: str) -> str:
        return f"{pair[:3]}_{pair[3:]}"

    @staticmethod
    def _normalize_instrument(instrument: str) -> str:
        return instrument.replace("_", "")

    @staticmethod
    def _exposure_from_payload(payload: Dict[str, Any]) -> PositionExposure:
        return PositionExposure(
            units=float(payload.get("units") or 0.0),
            average_price=float(payload["averagePrice"]) if payload.get("averagePrice") else None,
            unrealized_pnl=float(payload.get("unrealizedPL") or 0.0),
            realized_pnl=float(payload.get("pl") or 0.0),
            trade_ids=[str(item) for item in payload.get("tradeIDs", [])],
        )

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    @staticmethod
    def _format_price(value: float) -> str:
        return f"{value:.5f}"
