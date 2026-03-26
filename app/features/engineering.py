"""Feature engineering for the multi-horizon prediction pipeline."""

from typing import Dict

import pandas as pd

from app.models.signal import FeatureVector, MarketSnapshot


class FeatureEngineer:
    """Build model-ready features from recent market observations."""

    def build_features(
        self,
        pair: str,
        snapshot: MarketSnapshot,
        recent_ticks: pd.DataFrame,
    ) -> FeatureVector:
        """Generate a compact feature set for mock or real models."""

        frame = recent_ticks.copy()
        frame["return_1"] = frame["mid"].pct_change().fillna(0.0)
        frame["delta"] = frame["mid"].diff().fillna(0.0)

        momentum_5 = self._relative_change(frame, 5)
        momentum_10 = self._relative_change(frame, 10)
        momentum_30 = self._relative_change(frame, 30)
        volatility_10 = float(frame["return_1"].tail(10).std() or 0.0)
        volatility_30 = float(frame["return_1"].tail(30).std() or 0.0)

        ema_fast = float(frame["mid"].ewm(span=5, adjust=False).mean().iloc[-1])
        ema_slow = float(frame["mid"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema_gap = (ema_fast - ema_slow) / snapshot.mid_price

        recent_window = frame["mid"].tail(30)
        window_high = float(recent_window.max())
        window_low = float(recent_window.min())
        window_range = (window_high - window_low) / snapshot.mid_price if snapshot.mid_price else 0.0
        if window_high == window_low:
            price_position = 0.5
        else:
            price_position = (snapshot.mid_price - window_low) / (window_high - window_low)

        tick_direction = float(frame["delta"].tail(5).sum())
        if tick_direction > 0:
            tick_direction = 1.0
        elif tick_direction < 0:
            tick_direction = -1.0
        else:
            tick_direction = 0.0

        features: Dict[str, float] = {
            "momentum_5_bps": momentum_5 * 10000.0,
            "momentum_10_bps": momentum_10 * 10000.0,
            "momentum_30_bps": momentum_30 * 10000.0,
            "volatility_10_bps": volatility_10 * 10000.0,
            "volatility_30_bps": volatility_30 * 10000.0,
            "ema_gap_bps": ema_gap * 10000.0,
            "range_30_bps": window_range * 10000.0,
            "spread_bps": (snapshot.spread / snapshot.mid_price) * 10000.0,
            "price_position": float(price_position),
            "tick_direction": tick_direction,
            "micro_acceleration_bps": (momentum_5 - (momentum_10 / 2.0)) * 10000.0,
        }

        return FeatureVector(pair=pair, timestamp=snapshot.timestamp, values=features)

    @staticmethod
    def _relative_change(frame: pd.DataFrame, periods: int) -> float:
        """Return relative price change over the requested lookback."""

        if len(frame) <= periods:
            return 0.0

        latest = float(frame["mid"].iloc[-1])
        previous = float(frame["mid"].iloc[-(periods + 1)])
        if previous == 0.0:
            return 0.0
        return (latest - previous) / previous

