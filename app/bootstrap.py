"""Dependency wiring for API and bot entry points."""

from dataclasses import dataclass
from typing import Optional

from app.config.settings import Settings, get_settings
from app.data.mock_market_data import MockMarketDataProvider
from app.data.oanda_market_data import OandaMarketDataProvider
from app.data.oanda_trading import OandaTradingProvider
from app.features.engineering import FeatureEngineer
from app.models.interfaces import AbstractPredictionProvider
from app.models.model_loader import JoblibModelLoader
from app.persistence.supabase import SupabasePersistence
from app.services.access_control import AccessControlService
from app.services.market_data_service import MarketDataService
from app.services.prediction_service import RuleBasedPredictionProvider, SklearnPredictionProvider
from app.services.signal_service import SignalService
from app.services.subscriptions import SubscriptionService
from app.services.trading_service import TradingService
from app.utils.logging import configure_logging
from app.utils.monitoring import configure_monitoring


@dataclass
class AppContext:
    """Container for application-wide services."""

    settings: Settings
    market_data_service: MarketDataService
    feature_engineer: FeatureEngineer
    prediction_provider: AbstractPredictionProvider
    signal_service: SignalService
    subscription_service: SubscriptionService
    trading_service: TradingService
    access_control_service: AccessControlService
    persistence: Optional[SupabasePersistence]


def build_app_context() -> AppContext:
    """Create an application context with configured dependencies."""

    settings = get_settings()
    configure_logging(settings.log_level)
    configure_monitoring(settings)

    market_provider = _build_market_provider(settings)
    market_data_service = MarketDataService(market_provider)
    feature_engineer = FeatureEngineer()
    prediction_provider = _build_prediction_provider(settings)
    persistence = _build_persistence(settings)
    subscription_service = SubscriptionService(persistence=persistence)
    access_control_service = AccessControlService(settings=settings, persistence=persistence)
    signal_service = SignalService(
        settings=settings,
        market_data_service=market_data_service,
        feature_engineer=feature_engineer,
        prediction_provider=prediction_provider,
    )
    trading_service = TradingService(
        settings=settings,
        signal_service=signal_service,
        market_data_service=market_data_service,
        persistence=persistence,
        broker=_build_trading_provider(settings),
    )

    return AppContext(
        settings=settings,
        market_data_service=market_data_service,
        feature_engineer=feature_engineer,
        prediction_provider=prediction_provider,
        signal_service=signal_service,
        subscription_service=subscription_service,
        trading_service=trading_service,
        access_control_service=access_control_service,
        persistence=persistence,
    )


def _build_market_provider(settings: Settings):
    """Create the configured market data provider."""

    if settings.market_data_provider == "oanda":
        return OandaMarketDataProvider(settings)
    return MockMarketDataProvider(settings.available_pairs)


def _build_prediction_provider(settings: Settings) -> AbstractPredictionProvider:
    """Create the configured prediction provider."""

    if settings.prediction_provider == "sklearn":
        return SklearnPredictionProvider(JoblibModelLoader(settings.resolved_model_dir))
    return RuleBasedPredictionProvider()


def _build_persistence(settings: Settings) -> Optional[SupabasePersistence]:
    """Create the configured persistence backend."""

    if not settings.database_url:
        return None
    return SupabasePersistence(
        database_url=settings.database_url,
        pool_size=settings.database_pool_size,
        command_timeout_seconds=settings.database_command_timeout_seconds,
    )


def _build_trading_provider(settings: Settings) -> Optional[OandaTradingProvider]:
    """Create the broker execution provider when credentials exist."""

    if not settings.oanda_api_token or not settings.oanda_account_id:
        return None
    return OandaTradingProvider(settings)
