"""Abstract interfaces for pluggable providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd

from app.models.signal import FeatureVector, HorizonSignal, MarketSnapshot


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

