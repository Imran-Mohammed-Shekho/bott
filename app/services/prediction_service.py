"""Prediction providers for forex signal classification."""

import math
from typing import Dict

import pandas as pd

from app.models.interfaces import AbstractPredictionProvider
from app.models.model_loader import JoblibModelLoader, MockModelLoader
from app.models.signal import FeatureVector, HORIZONS, HorizonSignal, MarketSnapshot, SignalLabel


class MockPredictionProvider(AbstractPredictionProvider):
    """Deterministic mock predictor with horizon-specific scoring rules."""

    def __init__(self, model_loader: MockModelLoader):
        self._models = model_loader.load()
        self._weights = {
            "5s": {
                "momentum_5_bps": 0.36,
                "momentum_10_bps": 0.12,
                "volatility_10_bps": -0.22,
                "spread_bps": -0.10,
                "ema_gap_bps": 0.16,
                "tick_direction": 0.45,
                "price_position": 0.18,
                "micro_acceleration_bps": 0.22,
            },
            "10s": {
                "momentum_5_bps": 0.28,
                "momentum_10_bps": 0.20,
                "volatility_10_bps": -0.16,
                "spread_bps": -0.08,
                "ema_gap_bps": 0.18,
                "tick_direction": 0.28,
                "price_position": 0.14,
                "micro_acceleration_bps": 0.17,
            },
            "30s": {
                "momentum_10_bps": 0.22,
                "momentum_30_bps": 0.24,
                "volatility_30_bps": -0.12,
                "spread_bps": -0.05,
                "ema_gap_bps": 0.22,
                "range_30_bps": -0.06,
                "price_position": 0.11,
                "micro_acceleration_bps": 0.10,
            },
            "1m": {
                "momentum_10_bps": 0.18,
                "momentum_30_bps": 0.26,
                "volatility_30_bps": -0.10,
                "spread_bps": -0.04,
                "ema_gap_bps": 0.24,
                "range_30_bps": -0.04,
                "price_position": 0.10,
                "micro_acceleration_bps": 0.08,
            },
        }

    async def predict(
        self,
        pair: str,
        snapshot: MarketSnapshot,
        features: FeatureVector,
    ) -> Dict[str, HorizonSignal]:
        """Return a signal and confidence for each supported horizon."""

        results: Dict[str, HorizonSignal] = {}
        pair_bias = (sum(ord(character) for character in pair) % 5) * 0.03

        for horizon in HORIZONS:
            weighted_sum = 0.0
            for feature_name, weight in self._weights[horizon].items():
                weighted_sum += features.values.get(feature_name, 0.0) * weight

            raw_score = weighted_sum + pair_bias
            normalized_score = math.tanh(raw_score / 6.0)
            signal = self._classify(normalized_score)
            confidence = self._confidence(normalized_score, horizon)

            results[horizon] = HorizonSignal(signal=signal, confidence=confidence)

        return results

    @staticmethod
    def _classify(score: float) -> SignalLabel:
        """Map a continuous score to BUY, SELL, or HOLD."""

        if score >= 0.20:
            return SignalLabel.BUY
        if score <= -0.20:
            return SignalLabel.SELL
        return SignalLabel.HOLD

    @staticmethod
    def _confidence(score: float, horizon: str) -> float:
        """Generate a plausible confidence score from the signal strength."""

        base = 0.50 + (abs(score) * 0.28)
        if horizon == "30s":
            base += 0.03
        elif horizon == "1m":
            base += 0.05
        return round(min(base, 0.95), 2)


class SklearnPredictionProvider(AbstractPredictionProvider):
    """Inference provider backed by trained sklearn-compatible models."""

    def __init__(self, model_loader: JoblibModelLoader):
        self._models = model_loader.load()

    async def predict(
        self,
        pair: str,
        snapshot: MarketSnapshot,
        features: FeatureVector,
    ) -> Dict[str, HorizonSignal]:
        """Run trained model inference for each supported horizon."""

        feature_frame = pd.DataFrame([features.values])
        results: Dict[str, HorizonSignal] = {}

        for horizon in HORIZONS:
            model_spec = self._models[horizon]
            model = model_spec.model
            prepared_frame = self._prepare_features(model, feature_frame)

            predicted_label = str(model.predict(prepared_frame)[0]).upper()
            signal = self._to_signal_label(predicted_label)
            confidence = self._predict_confidence(model, prepared_frame, signal, model_spec.classes)
            results[horizon] = HorizonSignal(signal=signal, confidence=confidence)

        return results

    @staticmethod
    def _prepare_features(model: object, feature_frame: pd.DataFrame) -> pd.DataFrame:
        """Align features to the training-time schema if the model exposes it."""

        if hasattr(model, "feature_names_in_"):
            expected_columns = [str(item) for item in model.feature_names_in_]
            return feature_frame.reindex(columns=expected_columns, fill_value=0.0)
        return feature_frame

    @staticmethod
    def _predict_confidence(
        model: object,
        feature_frame: pd.DataFrame,
        signal: SignalLabel,
        classes: tuple[str, ...],
    ) -> float:
        """Return the model probability for the predicted signal when available."""

        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(feature_frame)[0]
            if not classes and hasattr(model, "classes_"):
                classes = tuple(str(item).upper() for item in model.classes_)
            probability_map = {
                str(label).upper(): float(probability)
                for label, probability in zip(classes, probabilities)
            }
            return round(float(probability_map.get(signal.value, max(probabilities))), 2)
        return 0.51

    @staticmethod
    def _to_signal_label(label: str) -> SignalLabel:
        """Map model output labels to BUY, SELL, or HOLD."""

        normalized = label.strip().upper()
        if normalized in {"BUY", "LONG", "UP"}:
            return SignalLabel.BUY
        if normalized in {"SELL", "SHORT", "DOWN"}:
            return SignalLabel.SELL
        return SignalLabel.HOLD
