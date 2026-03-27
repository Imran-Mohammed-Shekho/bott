"""Unit tests for token issuance and daily quota enforcement."""

import asyncio

import pytest

from app.config.settings import Settings
from app.services.access_control import AccessControlService, AccessDeniedError, QuotaExceededError


def test_issue_and_redeem_token_assigns_daily_limit() -> None:
    """Redeeming a token should activate access with the token's quota."""

    service = AccessControlService(Settings(display_timezone="UTC"))

    async def run() -> None:
        token = await service.issue_token(daily_limit=10, issued_by=1)
        status = await service.redeem_token(token.token, user_id=42, username="alice")
        assert status.user_id == 42
        assert status.daily_limit == 10
        assert status.remaining_today == 10
        assert status.granted_via_token == token.token

    asyncio.run(run())


def test_consume_request_enforces_daily_quota() -> None:
    """Users should be blocked after consuming the configured daily limit."""

    service = AccessControlService(Settings(display_timezone="UTC"))

    async def run() -> None:
        await service.set_user_quota(user_id=77, daily_limit=2, username="quota_user")
        await service.ensure_can_request(user_id=77, username="quota_user")
        first = await service.consume_request(user_id=77, username="quota_user")
        second = await service.consume_request(user_id=77, username="quota_user")

        assert first.remaining_today == 1
        assert second.remaining_today == 0

        with pytest.raises(QuotaExceededError):
            await service.ensure_can_request(user_id=77, username="quota_user")

    asyncio.run(run())


def test_admin_bypasses_quota_and_tokens() -> None:
    """Configured Telegram admins should always have access."""

    service = AccessControlService(
        Settings(display_timezone="UTC", admin_telegram_user_ids_csv="5389240816")
    )

    async def run() -> None:
        status = await service.ensure_can_request(user_id=5389240816, username="admin")
        assert status.remaining_today > 1000

    asyncio.run(run())


def test_disabled_user_loses_access() -> None:
    """Disabled users should be blocked from consuming more requests."""

    service = AccessControlService(Settings(display_timezone="UTC"))

    async def run() -> None:
        await service.set_user_quota(user_id=88, daily_limit=5)
        disabled = await service.deactivate_user(88)
        assert disabled is True

        with pytest.raises(AccessDeniedError):
            await service.ensure_can_request(user_id=88)

    asyncio.run(run())
