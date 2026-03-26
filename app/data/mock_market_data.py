"""Mock market data provider for local development."""

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List

import pandas as pd

from app.models.interfaces import AbstractMarketDataProvider
from app.models.signal import MarketSnapshot


DEFAULT_BASE_PRICES: Dict[str, float] = {
    "EURUSD": 1.0832,
    "GBPUSD": 1.2718,
    "USDJPY": 151.42,
    "USDCHF": 0.8924,
    "AUDUSD": 0.6615,
    "USDCAD": 1.3529,
    "NZDUSD": 0.6112,
    "EURGBP": 0.8519,
}


class MockMarketDataProvider(AbstractMarketDataProvider):
    """Generate deterministic synthetic prices suitable for local demos."""

    def __init__(self, available_pairs: Iterable[str]):
        self._available_pairs = list(available_pairs)
        self._base_prices = {
            pair: DEFAULT_BASE_PRICES.get(pair, 1.0 + (index * 0.1))
            for index, pair in enumerate(self._available_pairs)
        }

    async def fetch_snapshot(self, pair: str) -> MarketSnapshot:
        """Return a synthetic real-time market snapshot."""

        timestamp = datetime.now(timezone.utc)
        mid_price = self._mid_price(pair, timestamp)
        spread = self._spread(pair, timestamp)
        bid = mid_price - (spread / 2.0)
        ask = mid_price + (spread / 2.0)
        return MarketSnapshot(
            pair=pair,
            bid=bid,
            ask=ask,
            mid_price=mid_price,
            spread=spread,
            timestamp=timestamp,
        )

    async def fetch_recent_ticks(self, pair: str, lookback_seconds: int) -> pd.DataFrame:
        """Return recent synthetic one-second ticks for feature generation."""

        end_timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        phase = self._pair_phase(pair)
        rows: List[Dict[str, float]] = []

        for offset in range(lookback_seconds, -1, -1):
            timestamp = end_timestamp - timedelta(seconds=offset)
            mid_price = self._mid_price(pair, timestamp)
            spread = self._spread(pair, timestamp)
            bid = mid_price - (spread / 2.0)
            ask = mid_price + (spread / 2.0)
            volume = 100.0 + (20.0 * (1.0 + math.sin((timestamp.timestamp() / 6.0) + phase)))
            rows.append(
                {
                    "timestamp": timestamp,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid_price,
                    "spread": spread,
                    "volume": volume,
                }
            )

        return pd.DataFrame(rows)

    def _mid_price(self, pair: str, timestamp: datetime) -> float:
        """Compute a deterministic synthetic mid price."""

        base_price = self._base_prices[pair]
        phase = self._pair_phase(pair)
        current_time = timestamp.timestamp()
        wave = (
            0.00045 * math.sin((current_time / 9.0) + phase)
            + 0.00028 * math.cos((current_time / 17.0) + (phase / 2.0))
            + 0.00014 * math.sin((current_time / 31.0) + (phase / 3.0))
        )
        return base_price * (1.0 + wave)

    def _spread(self, pair: str, timestamp: datetime) -> float:
        """Compute a synthetic pair spread."""

        pip_size = 0.01 if pair.endswith("JPY") else 0.0001
        phase = self._pair_phase(pair)
        spread_pips = 0.7 + (0.5 * abs(math.sin((timestamp.timestamp() / 13.0) + phase)))
        return spread_pips * pip_size

    @staticmethod
    def _pair_phase(pair: str) -> float:
        """Return a stable per-pair phase offset."""

        return float(sum(ord(character) for character in pair) % 19)

