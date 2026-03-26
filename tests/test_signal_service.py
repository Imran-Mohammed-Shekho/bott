"""Unit tests for the signal orchestration layer."""

import asyncio
import os

from app.config.settings import get_settings
from app.bootstrap import build_app_context
from app.models.signal import HORIZONS
from app.services.signal_service import SignalService


os.environ["MARKET_DATA_PROVIDER"] = "mock"
os.environ["PREDICTION_PROVIDER"] = "mock"
get_settings.cache_clear()


def test_normalize_pair_accepts_slash_format() -> None:
    """Pairs should normalize cleanly."""

    assert SignalService.normalize_pair("eur/usd") == "EURUSD"


def test_signal_service_returns_all_horizons() -> None:
    """Signal responses should include every configured horizon."""

    app_context = build_app_context()
    response = asyncio.run(app_context.signal_service.get_signal("EURUSD"))

    assert response.pair == "EURUSD"
    assert response.display_pair == "EUR/USD"
    assert set(response.signals.keys()) == set(HORIZONS)
    for horizon_signal in response.signals.values():
        assert 0.0 <= horizon_signal.confidence <= 1.0


def test_mock_alias_normalizes_to_rule_based() -> None:
    """Legacy mock config should map to the rule-based engine."""

    app_context = build_app_context()
    assert app_context.settings.prediction_provider == "rule_based"
