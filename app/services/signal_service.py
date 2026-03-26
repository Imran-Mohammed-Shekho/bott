"""Core orchestration service for forex signal generation."""

from typing import List

from app.config.settings import Settings
from app.features.engineering import FeatureEngineer
from app.models.interfaces import AbstractPredictionProvider
from app.models.signal import SignalResponse
from app.services.market_data_service import MarketDataService


class SignalService:
    """Validate inputs and orchestrate market data, features, and predictions."""

    def __init__(
        self,
        settings: Settings,
        market_data_service: MarketDataService,
        feature_engineer: FeatureEngineer,
        prediction_provider: AbstractPredictionProvider,
    ):
        self._settings = settings
        self._market_data_service = market_data_service
        self._feature_engineer = feature_engineer
        self._prediction_provider = prediction_provider

    async def get_signal(self, pair: str) -> SignalResponse:
        """Return a signal response for a supported forex pair."""

        normalized_pair = self.resolve_pair(pair)
        snapshot, recent_ticks = await self._market_data_service.get_market_context(
            normalized_pair,
            lookback_seconds=self._settings.lookback_seconds,
        )
        features = self._feature_engineer.build_features(normalized_pair, snapshot, recent_ticks)
        predictions = await self._prediction_provider.predict(normalized_pair, snapshot, features)

        return SignalResponse(
            pair=normalized_pair,
            display_pair=self.display_pair(normalized_pair),
            signals=predictions,
            current_mid_price=snapshot.mid_price,
            spread=snapshot.spread,
            timestamp=snapshot.timestamp,
            risk_warning=self._settings.risk_warning,
            disclaimer=self._settings.disclaimer,
        )

    def list_pairs(self) -> List[str]:
        """Return the normalized list of supported pairs."""

        return self._settings.available_pairs

    def resolve_pair(self, pair: str) -> str:
        """Normalize and validate a requested forex pair."""

        normalized = self.normalize_pair(pair)
        if normalized not in self._settings.available_pairs:
            supported = ", ".join(self.display_pair(item) for item in self._settings.available_pairs)
            raise ValueError(f"Unsupported pair '{pair}'. Supported pairs: {supported}")
        return normalized

    @staticmethod
    def normalize_pair(pair: str) -> str:
        """Normalize a pair symbol to six uppercase letters without separators."""

        normalized = pair.strip().replace("/", "").upper()
        if len(normalized) != 6 or not normalized.isalpha():
            raise ValueError("Pairs must look like EURUSD or EUR/USD.")
        return normalized

    @staticmethod
    def display_pair(pair: str) -> str:
        """Format a normalized pair for user-facing output."""

        return f"{pair[:3]}/{pair[3:]}"
