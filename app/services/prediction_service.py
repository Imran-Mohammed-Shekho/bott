"""Prediction providers for forex signal classification."""

from dataclasses import dataclass
import math
from typing import Dict

import pandas as pd

from app.models.interfaces import AbstractPredictionProvider
from app.models.model_loader import JoblibModelLoader
from app.models.signal import FeatureVector, HORIZONS, HorizonSignal, MarketSnapshot, SignalLabel


@dataclass(frozen=True)
class HorizonRuleProfile:
    """Weight profile for one prediction horizon."""

    trend_weight: float
    timing_weight: float
    structure_weight: float
    volatility_penalty: float
    spread_penalty: float
    threshold: float
    hold_band: float


class RuleBasedPredictionProvider(AbstractPredictionProvider):
    """Rule-based predictor using trend, timing, and market-structure filters."""

    def __init__(self):
        self._profiles = {
            "5s": HorizonRuleProfile(0.28, 0.46, 0.20, 0.18, 0.22, 0.44, 0.16),
            "10s": HorizonRuleProfile(0.34, 0.40, 0.18, 0.15, 0.18, 0.42, 0.14),
            "30s": HorizonRuleProfile(0.44, 0.26, 0.16, 0.12, 0.14, 0.38, 0.12),
            "1m": HorizonRuleProfile(0.50, 0.18, 0.15, 0.10, 0.12, 0.34, 0.10),
        }

    async def predict(
        self,
        pair: str,
        snapshot: MarketSnapshot,
        features: FeatureVector,
    ) -> Dict[str, HorizonSignal]:
        """Return a rule-based signal and confidence for each supported horizon."""

        results: Dict[str, HorizonSignal] = {}

        for horizon in HORIZONS:
            profile = self._profiles[horizon]
            trend_score = self._trend_score(features.values, horizon)
            timing_score = self._timing_score(features.values, horizon)
            structure_score = self._structure_score(features.values, trend_score)
            penalty = self._penalty_score(features.values, profile)

            composite = (
                (trend_score * profile.trend_weight)
                + (timing_score * profile.timing_weight)
                + (structure_score * profile.structure_weight)
                - penalty
            )

            signal = self._classify(composite, trend_score, timing_score, profile)
            confidence = self._confidence(
                composite=composite,
                trend_score=trend_score,
                timing_score=timing_score,
                structure_score=structure_score,
                penalty=penalty,
                signal=signal,
            )
            results[horizon] = HorizonSignal(signal=signal, confidence=confidence)

        return results

    @staticmethod
    def _trend_score(values: Dict[str, float], horizon: str) -> float:
        """Measure higher-timeframe directional pressure."""

        ema_component = values.get("ema_gap_bps", 0.0) / 8.0
        if horizon in {"5s", "10s"}:
            momentum_component = (
                (values.get("momentum_10_bps", 0.0) * 0.7)
                + (values.get("momentum_5_bps", 0.0) * 0.3)
            ) / 8.0
        else:
            momentum_component = (
                (values.get("momentum_30_bps", 0.0) * 0.65)
                + (values.get("momentum_10_bps", 0.0) * 0.35)
            ) / 8.0
        return math.tanh(ema_component + momentum_component)

    @staticmethod
    def _timing_score(values: Dict[str, float], horizon: str) -> float:
        """Measure short-term trigger quality."""

        acceleration_component = values.get("micro_acceleration_bps", 0.0) / 6.0
        micro_momentum = values.get("momentum_5_bps", 0.0) / 6.0
        tick_component = values.get("tick_direction", 0.0) * (0.85 if horizon == "5s" else 0.65)
        return math.tanh((micro_momentum * 0.45) + (acceleration_component * 0.35) + tick_component)

    @staticmethod
    def _structure_score(values: Dict[str, float], trend_score: float) -> float:
        """Reward pullbacks in-trend and fade exhausted extremes."""

        price_position = values.get("price_position", 0.5)
        pullback = (0.55 - price_position) if trend_score >= 0 else (price_position - 0.45)
        return max(-1.0, min(1.0, pullback * 2.4))

    @staticmethod
    def _penalty_score(values: Dict[str, float], profile: HorizonRuleProfile) -> float:
        """Penalize signals in noisy or expensive market conditions."""

        spread_penalty = max(0.0, values.get("spread_bps", 0.0) - 1.5) / 6.0
        vol_penalty = max(0.0, values.get("volatility_10_bps", 0.0) - 3.0) / 8.0
        range_penalty = max(0.0, values.get("range_30_bps", 0.0) - 18.0) / 22.0
        return (
            (spread_penalty * profile.spread_penalty)
            + (vol_penalty * profile.volatility_penalty)
            + (range_penalty * 0.08)
        )

    @staticmethod
    def _classify(
        composite: float,
        trend_score: float,
        timing_score: float,
        profile: HorizonRuleProfile,
    ) -> SignalLabel:
        """Map the rule output to BUY, SELL, or HOLD."""

        if abs(composite) < profile.hold_band:
            return SignalLabel.HOLD

        if composite > 0:
            if trend_score < -0.08 or timing_score < -0.20:
                return SignalLabel.HOLD
            if composite >= profile.threshold:
                return SignalLabel.BUY
        else:
            if trend_score > 0.08 or timing_score > 0.20:
                return SignalLabel.HOLD
            if composite <= -profile.threshold:
                return SignalLabel.SELL

        return SignalLabel.HOLD

    @staticmethod
    def _confidence(
        composite: float,
        trend_score: float,
        timing_score: float,
        structure_score: float,
        penalty: float,
        signal: SignalLabel,
    ) -> float:
        """Estimate confidence from directional agreement and market quality."""

        directional_agreement = 0.0
        for component in (trend_score, timing_score, structure_score):
            if signal == SignalLabel.BUY and component > 0:
                directional_agreement += abs(component)
            elif signal == SignalLabel.SELL and component < 0:
                directional_agreement += abs(component)
            elif signal == SignalLabel.HOLD:
                directional_agreement += 0.15

        base = 0.50 + (abs(composite) * 0.22)
        base += min(directional_agreement / 8.0, 0.14)
        base -= min(max(penalty, 0.0), 0.18)
        if signal == SignalLabel.HOLD:
            base = min(base, 0.64)
        return round(min(base, 0.95), 2)


class MockPredictionProvider(RuleBasedPredictionProvider):
    """Backward-compatible alias for the rule-based predictor."""

    pass


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
