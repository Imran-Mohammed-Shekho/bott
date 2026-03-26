"""OANDA-backed live market data provider."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List

import httpx
import pandas as pd

from app.config.settings import Settings
from app.models.interfaces import AbstractMarketDataProvider
from app.models.signal import MarketSnapshot


class OandaMarketDataProvider(AbstractMarketDataProvider):
    """Fetch live forex quotes and recent candles from OANDA v20."""

    def __init__(self, settings: Settings):
        self._settings = settings
        if not settings.oanda_api_token or not settings.oanda_account_id:
            raise ValueError(
                "OANDA_API_TOKEN and OANDA_ACCOUNT_ID are required when MARKET_DATA_PROVIDER=oanda."
            )

    async def fetch_snapshot(self, pair: str) -> MarketSnapshot:
        """Fetch the latest account-scoped price for a pair."""

        instrument = self._instrument_name(pair)
        payload = await self._get_json(
            path=f"/accounts/{self._settings.oanda_account_id}/pricing",
            params={"instruments": instrument},
        )
        prices = payload.get("prices", [])
        if not prices:
            raise RuntimeError(f"OANDA returned no price for {instrument}.")

        price = prices[0]
        bid = self._extract_price_side(price, side="bids", fallback_key="closeoutBid")
        ask = self._extract_price_side(price, side="asks", fallback_key="closeoutAsk")
        timestamp = pd.to_datetime(price["time"], utc=True).to_pydatetime()
        timestamp = timestamp.astimezone(timezone.utc)
        mid_price = (bid + ask) / 2.0

        return MarketSnapshot(
            pair=pair,
            bid=bid,
            ask=ask,
            mid_price=mid_price,
            spread=ask - bid,
            timestamp=timestamp,
        )

    async def fetch_recent_ticks(self, pair: str, lookback_seconds: int) -> pd.DataFrame:
        """Fetch recent S5 candles and convert them into the shared schema."""

        instrument = self._instrument_name(pair)
        count = max(int(lookback_seconds / 5) + 10, 40)
        payload = await self._get_json(
            path=f"/instruments/{instrument}/candles",
            params={"price": "MBA", "granularity": "S5", "count": count},
        )
        candles = payload.get("candles", [])
        if not candles:
            raise RuntimeError(f"OANDA returned no candles for {instrument}.")

        rows: List[Dict[str, Any]] = []
        for candle in candles:
            mid = candle.get("mid")
            bid = candle.get("bid")
            ask = candle.get("ask")
            if not mid:
                continue

            mid_close = float(mid["c"])
            bid_close = float(bid["c"]) if bid else mid_close
            ask_close = float(ask["c"]) if ask else mid_close
            rows.append(
                {
                    "timestamp": pd.to_datetime(candle["time"], utc=True),
                    "bid": bid_close,
                    "ask": ask_close,
                    "mid": mid_close,
                    "spread": ask_close - bid_close,
                    "volume": float(candle.get("volume", 0.0)),
                }
            )

        if not rows:
            raise RuntimeError(f"OANDA returned candles without usable prices for {instrument}.")

        return pd.DataFrame(rows)

    async def _get_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a GET request against OANDA's REST API."""

        base_url = self._settings.oanda_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self._settings.oanda_api_token}",
            "Accept-Datetime-Format": "RFC3339",
        }

        async with httpx.AsyncClient(timeout=self._settings.market_data_timeout_seconds) as client:
            response = await client.get(f"{base_url}{path}", params=params, headers=headers)

        response.raise_for_status()
        payload = response.json()
        if payload.get("errorMessage"):
            raise RuntimeError(str(payload["errorMessage"]))
        return payload

    @staticmethod
    def _instrument_name(pair: str) -> str:
        """Convert EURUSD into OANDA's EUR_USD instrument format."""

        return f"{pair[:3]}_{pair[3:]}"

    @staticmethod
    def _extract_price_side(price: Dict[str, Any], side: str, fallback_key: str) -> float:
        """Extract bid or ask from an OANDA price payload."""

        levels = price.get(side) or []
        if levels:
            return float(levels[0]["price"])
        return float(price[fallback_key])
