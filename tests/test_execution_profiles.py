"""Unit tests for encrypted execution profile storage."""

import asyncio

from app.config.settings import Settings
from app.services.execution_profiles import ExecutionProfileService


FERNET_TEST_KEY = "jR4B6E0gThEMQ7iO2l2Mdwv8A9dM8gM1cSxC4hZ3S2Q="


def test_connect_user_encrypts_and_restores_session() -> None:
    """Connected user sessions should be stored encrypted and decrypt cleanly."""

    service = ExecutionProfileService(
        Settings(
            display_timezone="UTC",
            public_app_url="https://example.com",
            session_encryption_key=FERNET_TEST_KEY,
        )
    )

    async def run() -> None:
        token = await service.issue_connect_token(user_id=123)
        status = await service.connect_user(
            token=token.token,
            storage_state_json='{"cookies":[{"name":"sid","value":"abc"}],"origins":[]}',
            autotrade_enabled=True,
            trade_amount=2,
            expiration_label="M5",
            signal_horizon="1m",
        )
        payload = await service.decrypt_session(123)
        assert status.has_session is True
        assert status.autotrade_enabled is True
        assert payload["cookies"][0]["value"] == "abc"

    asyncio.run(run())


def test_build_connect_url_uses_api_prefix() -> None:
    """Connect links should point to the rendered connect endpoint."""

    service = ExecutionProfileService(
        Settings(
            display_timezone="UTC",
            public_app_url="https://example.com",
            session_encryption_key=FERNET_TEST_KEY,
        )
    )

    assert service.build_connect_url("abc123") == "https://example.com/api/v1/connect/abc123"


def test_direct_session_save_and_disconnect() -> None:
    """Telegram-captured session JSON should save and later disconnect cleanly."""

    service = ExecutionProfileService(
        Settings(
            display_timezone="UTC",
            public_app_url="https://example.com",
            session_encryption_key=FERNET_TEST_KEY,
        )
    )

    async def run() -> None:
        status = await service.save_session_json(
            user_id=999,
            storage_state_json='{"cookies":[{"name":"sid","value":"xyz"}],"origins":[]}',
        )
        payload = await service.decrypt_session(999)
        removed = await service.disconnect_profile(999)

        assert status.has_session is True
        assert payload["cookies"][0]["value"] == "xyz"
        assert removed is True
        assert await service.get_profile_status(999) is None

    asyncio.run(run())
