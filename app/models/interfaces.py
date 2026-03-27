"""Abstract interfaces for pluggable providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

import pandas as pd

from app.models.signal import FeatureVector, HorizonSignal, MarketSnapshot
from app.models.trading import (
    AccountSummary,
    ClosePositionRequest,
    ClosePositionResponse,
    MarketOrderRequest,
    MarketOrderResponse,
    PositionSummary,
)


class AbstractMarketDataProvider(ABC):
    """Interface for market data providers."""

    @abstractmethod
    async def fetch_snapshot(self, pair: str) -> MarketSnapshot:
        """Return the latest quote snapshot for a pair."""

    @abstractmethod
    async def fetch_recent_ticks(self, pair: str, lookback_seconds: int) -> pd.DataFrame:
        """Return recent price observations used for feature engineering."""


class AbstractPredictionProvider(ABC):
    """Interface for prediction providers."""

    @abstractmethod
    async def predict(
        self,
        pair: str,
        snapshot: MarketSnapshot,
        features: FeatureVector,
    ) -> Dict[str, HorizonSignal]:
        """Return trading signals for each configured horizon."""


class AbstractModelLoader(ABC):
    """Interface for loading model metadata or trained artifacts."""

    @abstractmethod
    def load(self) -> Dict[str, Any]:
        """Load model artifacts or metadata."""


class AbstractExecutionProvider(ABC):
    """Interface for live trade execution backends."""

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Return the live account summary."""

    @abstractmethod
    async def list_open_positions(self) -> List[PositionSummary]:
        """Return the currently open positions."""

    @abstractmethod
    async def place_market_order(self, request: MarketOrderRequest) -> MarketOrderResponse:
        """Place a live market order."""

    @abstractmethod
    async def close_position(
        self,
        pair: str,
        request: ClosePositionRequest,
    ) -> ClosePositionResponse:
        """Close an open position."""
