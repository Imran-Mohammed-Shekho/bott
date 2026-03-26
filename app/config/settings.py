"""Runtime settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Set
from zoneinfo import ZoneInfo

from pydantic import BaseSettings, validator


class Settings(BaseSettings):
    """Application settings."""

    app_name: str = "Forex Signals Bot"
    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    telegram_bot_token: Optional[str] = None
    telegram_webhook_url: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None
    admin_telegram_user_ids_csv: str = ""
    admin_api_key: Optional[str] = None
    market_data_provider: str = "mock"
    prediction_provider: str = "rule_based"
    trade_mode: str = "paper"
    default_order_units: int = 100
    max_order_units: int = 1000
    max_open_positions: int = 3
    max_daily_loss_percent: float = 2.0
    max_margin_closeout_percent: float = 0.5
    market_data_timeout_seconds: float = 10.0
    lookback_seconds: int = 300
    database_url: Optional[str] = None
    database_pool_size: int = 5
    database_command_timeout_seconds: float = 15.0
    model_dir: str = "artifacts/models"
    oanda_environment: str = "practice"
    oanda_api_token: Optional[str] = None
    oanda_account_id: Optional[str] = None
    oanda_base_url: str = "https://api-fxpractice.oanda.com/v3"
    sentry_dsn: Optional[str] = None
    sentry_traces_sample_rate: float = 0.2
    sentry_profiles_sample_rate: float = 0.0
    display_timezone: str = "Asia/Baghdad"
    broker_style: str = "generic"
    default_watch_interval_seconds: int = 30
    min_watch_interval_seconds: int = 5
    max_watch_interval_seconds: int = 300
    available_pairs_csv: str = (
        "EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURGBP"
    )
    disclaimer: str = "ئەم ئاماژەیە تاقیکارییە و ڕاوێژی دارایی نییە."
    risk_warning: str = (
        "بە ڕێکخستنی توندی مەترسی کار بکە. ئاماژە کورتخایەنەکان زوو دەگۆڕێن."
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @validator(
        "default_watch_interval_seconds",
        "min_watch_interval_seconds",
        "max_watch_interval_seconds",
        "default_order_units",
        "max_order_units",
        "max_open_positions",
        "database_pool_size",
    )
    def validate_positive_interval(cls, value: int) -> int:
        """Ensure configured intervals are positive."""

        if value <= 0:
            raise ValueError("Watch intervals must be positive integers.")
        return value

    @validator("lookback_seconds")
    def validate_lookback_seconds(cls, value: int) -> int:
        """Ensure configured lookback is positive."""

        if value <= 0:
            raise ValueError("LOOKBACK_SECONDS must be positive.")
        return value

    @validator("market_data_timeout_seconds")
    def validate_market_data_timeout(cls, value: float) -> float:
        """Ensure configured upstream timeout is positive."""

        if value <= 0:
            raise ValueError("MARKET_DATA_TIMEOUT_SECONDS must be positive.")
        return value

    @validator("database_command_timeout_seconds")
    def validate_database_timeout(cls, value: float) -> float:
        """Ensure database timeout is positive."""

        if value <= 0:
            raise ValueError("DATABASE_COMMAND_TIMEOUT_SECONDS must be positive.")
        return value

    @validator("market_data_provider")
    def validate_market_data_provider(cls, value: str) -> str:
        """Restrict market data provider choices."""

        normalized = value.strip().lower()
        if normalized not in {"mock", "oanda"}:
            raise ValueError("MARKET_DATA_PROVIDER must be 'mock' or 'oanda'.")
        return normalized

    @validator("prediction_provider")
    def validate_prediction_provider(cls, value: str) -> str:
        """Restrict prediction provider choices."""

        normalized = value.strip().lower()
        if normalized == "mock":
            return "rule_based"
        if normalized not in {"rule_based", "sklearn"}:
            raise ValueError("PREDICTION_PROVIDER must be 'rule_based', 'mock', or 'sklearn'.")
        return normalized

    @validator("trade_mode")
    def validate_trade_mode(cls, value: str) -> str:
        """Restrict trading mode choices."""

        normalized = value.strip().lower()
        if normalized not in {"paper", "live"}:
            raise ValueError("TRADE_MODE must be 'paper' or 'live'.")
        return normalized

    @validator("display_timezone")
    def validate_display_timezone(cls, value: str) -> str:
        """Ensure the configured display timezone exists."""

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("DISPLAY_TIMEZONE must be a valid IANA timezone.") from exc
        return value

    @validator("broker_style")
    def validate_broker_style(cls, value: str) -> str:
        """Restrict broker-style output choices."""

        normalized = value.strip().lower()
        if normalized not in {"generic", "pocket_option"}:
            raise ValueError("BROKER_STYLE must be 'generic' or 'pocket_option'.")
        return normalized

    @validator("telegram_webhook_url")
    def validate_telegram_webhook_url(cls, value: Optional[str]) -> Optional[str]:
        """Ensure webhook registration uses HTTPS when configured."""

        if value is None:
            return value
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        if not normalized.startswith("https://"):
            raise ValueError("TELEGRAM_WEBHOOK_URL must start with https://")
        return normalized

    @validator("telegram_webhook_secret")
    def validate_telegram_webhook_secret(cls, value: Optional[str]) -> Optional[str]:
        """Normalize the optional Telegram webhook secret token."""

        if value is None:
            return value
        normalized = value.strip()
        return normalized or None

    @validator("max_daily_loss_percent", "max_margin_closeout_percent")
    def validate_fractional_limits(cls, value: float) -> float:
        """Ensure fractional risk controls are positive."""

        if value <= 0:
            raise ValueError("Risk limit values must be positive.")
        return value

    @property
    def available_pairs(self) -> List[str]:
        """Return normalized supported forex pairs."""

        pairs = []
        for raw_pair in self.available_pairs_csv.split(","):
            pair = raw_pair.strip().replace("/", "").upper()
            if pair:
                pairs.append(pair)
        return pairs

    @property
    def admin_telegram_user_ids(self) -> Set[int]:
        """Return the configured admin Telegram user IDs."""

        ids: Set[int] = set()
        for raw_value in self.admin_telegram_user_ids_csv.split(","):
            normalized = raw_value.strip()
            if normalized:
                ids.add(int(normalized))
        return ids

    @property
    def resolved_model_dir(self) -> Path:
        """Return the configured model directory."""

        return Path(self.model_dir).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
