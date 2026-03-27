"""User-managed execution profiles backed by encrypted session storage."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.models.execution import ExecutionConnectToken, ExecutionProfileStatus, UserExecutionProfile
from app.persistence.supabase import SupabasePersistence
from app.services.session_cipher import SessionCipher


class ExecutionProfileService:
    """Create connect links, store encrypted sessions, and manage profile settings."""

    def __init__(
        self,
        settings: Settings,
        persistence: Optional[SupabasePersistence] = None,
    ):
        self._settings = settings
        self._persistence = persistence
        self._timezone = ZoneInfo(settings.display_timezone)
        self._cipher = None
        self._connect_tokens: Dict[str, ExecutionConnectToken] = {}
        self._profiles: Dict[int, UserExecutionProfile] = {}
        self._lock: Optional[asyncio.Lock] = None

    async def issue_connect_token(self, user_id: int) -> ExecutionConnectToken:
        """Create a one-time token for the authenticated connect page."""

        now = datetime.now(self._timezone)
        record = ExecutionConnectToken(
            token=secrets.token_urlsafe(24),
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(minutes=self._settings.connect_token_ttl_minutes),
        )
        if self._persistence is not None:
            return await self._persistence.create_execution_connect_token(record)
        async with self._get_lock():
            self._connect_tokens[record.token] = record
        return record

    def build_connect_url(self, token: str) -> str:
        """Return the full public URL for the connect page."""

        base_url = self._settings.resolved_public_app_url
        if not base_url:
            raise RuntimeError("PUBLIC_APP_URL or TELEGRAM_WEBHOOK_URL is required for /connect.")
        return f"{base_url}/api/v1/connect/{token}"

    async def get_connect_token(self, token: str) -> Optional[ExecutionConnectToken]:
        """Return a connect token when it exists."""

        if self._persistence is not None:
            return await self._persistence.get_execution_connect_token(token)
        async with self._get_lock():
            return self._connect_tokens.get(token)

    async def connect_user(
        self,
        token: str,
        storage_state_json: str,
        autotrade_enabled: bool = False,
        trade_amount: Optional[int] = None,
        expiration_label: Optional[str] = None,
        signal_horizon: Optional[str] = None,
    ) -> ExecutionProfileStatus:
        """Consume a connect token and upsert the encrypted execution profile."""

        now = datetime.now(self._timezone)
        connect_token = await self._consume_connect_token(token, now)
        if connect_token is None:
            raise RuntimeError("Connect link is invalid, expired, or already used.")

        try:
            storage_state = json.loads(storage_state_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Storage state must be valid JSON.") from exc

        profile = UserExecutionProfile(
            user_id=connect_token.user_id,
            provider="pocket_option_browser",
            encrypted_session=self._get_cipher().encrypt_json(storage_state),
            autotrade_enabled=autotrade_enabled,
            trade_amount=trade_amount or self._settings.pocket_option_trade_amount,
            expiration_label=expiration_label or self._settings.pocket_option_expiration_label,
            signal_horizon=signal_horizon or "1m",
            created_at=now,
            updated_at=now,
        )
        profile = await self._upsert_profile(profile)
        return self._status_from_profile(profile)

    async def get_profile(self, user_id: int) -> Optional[UserExecutionProfile]:
        """Return the raw stored execution profile for a user."""

        if self._persistence is not None:
            return await self._persistence.get_user_execution_profile(user_id)
        async with self._get_lock():
            return self._profiles.get(user_id)

    async def get_profile_status(self, user_id: int) -> Optional[ExecutionProfileStatus]:
        """Return a user-facing status view for a stored profile."""

        profile = await self.get_profile(user_id)
        if profile is None:
            return None
        return self._status_from_profile(profile)

    async def decrypt_session(self, user_id: int) -> Dict:
        """Return the decrypted stored session for browser execution."""

        profile = await self.get_profile(user_id)
        if profile is None:
            raise RuntimeError("No execution profile is connected for this user.")
        return self._get_cipher().decrypt_json(profile.encrypted_session)

    async def set_autotrade(self, user_id: int, enabled: bool) -> ExecutionProfileStatus:
        """Enable or disable autotrading for a connected profile."""

        return self._status_from_profile(
            await self._update_profile(user_id, autotrade_enabled=enabled)
        )

    async def set_trade_amount(self, user_id: int, amount: int) -> ExecutionProfileStatus:
        """Update the stored trade amount."""

        if amount <= 0:
            raise ValueError("Trade amount must be greater than zero.")
        return self._status_from_profile(await self._update_profile(user_id, trade_amount=amount))

    async def set_expiration_label(self, user_id: int, label: str) -> ExecutionProfileStatus:
        """Update the stored expiration label."""

        normalized = label.strip().upper()
        if not normalized:
            raise ValueError("Expiration label is required.")
        return self._status_from_profile(
            await self._update_profile(user_id, expiration_label=normalized)
        )

    async def set_signal_horizon(self, user_id: int, horizon: str) -> ExecutionProfileStatus:
        """Update the stored signal horizon used for autotrading."""

        return self._status_from_profile(
            await self._update_profile(user_id, signal_horizon=horizon.strip().lower())
        )

    async def _consume_connect_token(
        self,
        token: str,
        consumed_at: datetime,
    ) -> Optional[ExecutionConnectToken]:
        if self._persistence is not None:
            return await self._persistence.consume_execution_connect_token(token, consumed_at)

        async with self._get_lock():
            record = self._connect_tokens.get(token)
            if (
                record is None
                or not record.is_active
                or record.used_at is not None
                or record.expires_at < consumed_at
            ):
                return None
            record.used_at = consumed_at
            record.is_active = False
            return record

    async def _upsert_profile(self, profile: UserExecutionProfile) -> UserExecutionProfile:
        if self._persistence is not None:
            return await self._persistence.upsert_user_execution_profile(profile)
        async with self._get_lock():
            existing = self._profiles.get(profile.user_id)
            if existing is not None:
                profile = profile.copy(update={"created_at": existing.created_at})
            self._profiles[profile.user_id] = profile
        return profile

    async def _update_profile(self, user_id: int, **updates) -> UserExecutionProfile:
        profile = await self.get_profile(user_id)
        if profile is None:
            raise RuntimeError("No execution profile is connected yet. Use /connect first.")
        updated = profile.copy(update={**updates, "updated_at": datetime.now(self._timezone)})
        return await self._upsert_profile(updated)

    @staticmethod
    def _status_from_profile(profile: UserExecutionProfile) -> ExecutionProfileStatus:
        return ExecutionProfileStatus(
            user_id=profile.user_id,
            provider=profile.provider,
            has_session=True,
            autotrade_enabled=profile.autotrade_enabled,
            trade_amount=profile.trade_amount,
            expiration_label=profile.expiration_label,
            signal_horizon=profile.signal_horizon,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _get_lock(self) -> asyncio.Lock:
        """Create the lock lazily so sync construction works on Python 3.9."""

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_cipher(self) -> SessionCipher:
        """Create the encryption helper lazily so non-connect flows can boot without it."""

        if self._cipher is None:
            self._cipher = SessionCipher(self._settings)
        return self._cipher
