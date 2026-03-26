"""Monitoring bootstrap."""

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.config.settings import Settings


_SENTRY_INITIALIZED = False


def configure_monitoring(settings: Settings) -> None:
    """Initialize Sentry once when configured."""

    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED or not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        integrations=[FastApiIntegration(transaction_style="endpoint")],
        send_default_pii=False,
    )
    _SENTRY_INITIALIZED = True
