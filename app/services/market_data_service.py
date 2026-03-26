"""Service wrapper around the configured market data provider."""

from typing import Tuple

import pandas as pd

from app.models.interfaces import AbstractMarketDataProvider
from app.models.signal import MarketSnapshot


class MarketDataService:
    """Load current and recent market data for signal generation."""

    def __init__(self, provider: AbstractMarketDataProvider):
        self._provider = provider

    async def get_market_context(
        self,
        pair: str,
        lookback_seconds: int = 90,
    ) -> Tuple[MarketSnapshot, pd.DataFrame]:
        """Fetch the current snapshot and recent ticks for a pair."""

        snapshot = await self._provider.fetch_snapshot(pair)
        recent_ticks = await self._provider.fetch_recent_ticks(pair, lookback_seconds)
        return snapshot, recent_ticks

