"""Access-token issuance and daily quota enforcement for Telegram users."""

from __future__ import annotations

import asyncio
import secrets
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.models.access import AccessTokenRecord, UserAccessRecord, UserQuotaStatus
from app.persistence.supabase import SupabasePersistence


class AccessControlError(Exception):
    """Base error for access-control failures."""


class AccessDeniedError(AccessControlError):
    """Raised when a user has no active access to the bot."""


class QuotaExceededError(AccessControlError):
    """Raised when a user has exhausted the daily request budget."""

    def __init__(self, status: UserQuotaStatus):
        super().__init__("Daily request quota exhausted.")
        self.status = status


class AccessControlService:
    """Manage admin-issued tokens, direct user grants, and daily usage quotas."""

    def __init__(
        self,
        settings: Settings,
        persistence: Optional[SupabasePersistence] = None,
    ):
        self._settings = settings
        self._persistence = persistence
        self._timezone = ZoneInfo(settings.display_timezone)
        self._tokens: Dict[str, AccessTokenRecord] = {}
        self._user_access: Dict[int, UserAccessRecord] = {}
        self._daily_usage: Dict[Tuple[int, date], int] = {}
        self._lock: Optional[asyncio.Lock] = None

    async def issue_token(self, daily_limit: int, issued_by: int) -> AccessTokenRecord:
        """Create a redeemable access token with a fixed daily quota."""

        if daily_limit <= 0:
            raise ValueError("Daily limit must be greater than zero.")

        record = AccessTokenRecord(
            token=secrets.token_hex(12).upper(),
            daily_limit=daily_limit,
            issued_by=issued_by,
            issued_at=datetime.now(self._timezone),
        )
        if self._persistence is not None:
            return await self._persistence.create_access_token(record)
        async with self._get_lock():
            self._tokens[record.token] = record
        return record

    async def redeem_token(
        self,
        token: str,
        user_id: int,
        username: Optional[str] = None,
    ) -> UserQuotaStatus:
        """Redeem an admin-issued token and activate access for the caller."""

        normalized_token = token.strip().upper()
        if not normalized_token:
            raise AccessDeniedError("Access token is required.")

        redeemed_at = datetime.now(self._timezone)
        if self._persistence is not None:
            record = await self._persistence.redeem_access_token(
                token=normalized_token,
                user_id=user_id,
                username=username,
                redeemed_at=redeemed_at,
            )
            if record is None:
                raise AccessDeniedError("Access token is invalid, expired, or already used.")
        else:
            async with self._get_lock():
                token_record = self._tokens.get(normalized_token)
                if (
                    token_record is None
                    or not token_record.is_active
                    or token_record.redeemed_by is not None
                ):
                    raise AccessDeniedError("Access token is invalid, expired, or already used.")
                token_record.redeemed_by = user_id
                token_record.redeemed_at = redeemed_at
                token_record.is_active = False
                record = UserAccessRecord(
                    user_id=user_id,
                    username=username,
                    daily_limit=token_record.daily_limit,
                    is_active=True,
                    granted_at=redeemed_at,
                    granted_via_token=normalized_token,
                )
                self._user_access[user_id] = record

        return await self.get_user_status(user_id, username=username, fallback_record=record)

    async def set_user_quota(
        self,
        user_id: int,
        daily_limit: int,
        username: Optional[str] = None,
        granted_via_token: Optional[str] = None,
    ) -> UserQuotaStatus:
        """Create or update direct bot access for a user."""

        if daily_limit <= 0:
            raise ValueError("Daily limit must be greater than zero.")

        record = UserAccessRecord(
            user_id=user_id,
            username=username,
            daily_limit=daily_limit,
            is_active=True,
            granted_at=datetime.now(self._timezone),
            granted_via_token=granted_via_token,
        )
        if self._persistence is not None:
            record = await self._persistence.upsert_user_access(record)
        else:
            async with self._get_lock():
                self._user_access[user_id] = record

        return await self.get_user_status(user_id, username=username, fallback_record=record)

    async def deactivate_user(self, user_id: int) -> bool:
        """Disable a user's bot access without deleting usage history."""

        if self._persistence is not None:
            return await self._persistence.set_user_active(user_id, is_active=False)

        async with self._get_lock():
            record = self._user_access.get(user_id)
            if record is None:
                return False
            record.is_active = False
        return True

    async def get_user_status(
        self,
        user_id: int,
        username: Optional[str] = None,
        fallback_record: Optional[UserAccessRecord] = None,
    ) -> Optional[UserQuotaStatus]:
        """Return the caller's current quota state."""

        if user_id in self._settings.admin_telegram_user_ids:
            return self._admin_status(user_id)

        usage_date = self._usage_date()
        record = fallback_record
        if record is None:
            if self._persistence is not None:
                record = await self._persistence.get_user_access(user_id)
            else:
                async with self._get_lock():
                    record = self._user_access.get(user_id)
        if record is None:
            return None

        if username and username != record.username:
            record = await self._refresh_username(record, username)

        used_today = await self._get_daily_usage(user_id, usage_date)
        return self._build_status(record, used_today, usage_date)

    async def list_user_statuses(self) -> List[UserQuotaStatus]:
        """List all granted users with today's remaining quota."""

        usage_date = self._usage_date()
        if self._persistence is not None:
            records = await self._persistence.list_user_access()
        else:
            async with self._get_lock():
                records = list(self._user_access.values())

        statuses = []
        for record in records:
            used_today = await self._get_daily_usage(record.user_id, usage_date)
            statuses.append(self._build_status(record, used_today, usage_date))
        return sorted(statuses, key=lambda item: (item.is_active is False, item.user_id))

    async def ensure_can_request(
        self,
        user_id: int,
        username: Optional[str] = None,
    ) -> UserQuotaStatus:
        """Validate that a user may request another prediction right now."""

        status = await self.get_user_status(user_id, username=username)
        if status is None or not status.is_active:
            raise AccessDeniedError(
                "Access is not active for your account. Ask admin for a token and use /redeem TOKEN."
            )
        if status.remaining_today <= 0:
            raise QuotaExceededError(status)
        return status

    async def consume_request(
        self,
        user_id: int,
        username: Optional[str] = None,
        amount: int = 1,
    ) -> UserQuotaStatus:
        """Consume one or more daily prediction requests for a user."""

        if amount <= 0:
            raise ValueError("Consumed request amount must be positive.")
        if user_id in self._settings.admin_telegram_user_ids:
            return self._admin_status(user_id)

        status = await self.ensure_can_request(user_id, username=username)
        if status.remaining_today < amount:
            raise QuotaExceededError(status)

        usage_date = status.usage_date
        used_today = await self._increment_daily_usage(user_id, usage_date, amount)
        refreshed = await self.get_user_status(user_id, username=username)
        if refreshed is None:
            raise AccessDeniedError("Access disappeared during request accounting.")
        refreshed.used_today = used_today
        refreshed.remaining_today = max(refreshed.daily_limit - used_today, 0)
        return refreshed

    async def _refresh_username(
        self,
        record: UserAccessRecord,
        username: Optional[str],
    ) -> UserAccessRecord:
        """Persist a fresher username when Telegram provides one."""

        if not username:
            return record
        updated = record.copy(update={"username": username})
        if self._persistence is not None:
            return await self._persistence.upsert_user_access(updated)
        async with self._get_lock():
            self._user_access[record.user_id] = updated
        return updated

    async def _get_daily_usage(self, user_id: int, usage_date: date) -> int:
        """Return the number of consumed requests for a user and day."""

        if self._persistence is not None:
            return await self._persistence.get_daily_usage(user_id, usage_date)
        async with self._get_lock():
            return self._daily_usage.get((user_id, usage_date), 0)

    async def _increment_daily_usage(self, user_id: int, usage_date: date, amount: int) -> int:
        """Atomically add to a user's usage counter."""

        if self._persistence is not None:
            return await self._persistence.increment_daily_usage(user_id, usage_date, amount)
        async with self._get_lock():
            key = (user_id, usage_date)
            self._daily_usage[key] = self._daily_usage.get(key, 0) + amount
            return self._daily_usage[key]

    def _build_status(
        self,
        record: UserAccessRecord,
        used_today: int,
        usage_date: date,
    ) -> UserQuotaStatus:
        """Compose a user-facing quota status view."""

        remaining_today = max(record.daily_limit - used_today, 0)
        return UserQuotaStatus(
            user_id=record.user_id,
            username=record.username,
            daily_limit=record.daily_limit,
            used_today=used_today,
            remaining_today=remaining_today,
            usage_date=usage_date,
            is_active=record.is_active,
            granted_at=record.granted_at,
            granted_via_token=record.granted_via_token,
        )

    def _admin_status(self, user_id: int) -> UserQuotaStatus:
        """Return a synthetic unlimited status for admins."""

        usage_date = self._usage_date()
        return UserQuotaStatus(
            user_id=user_id,
            username="admin",
            daily_limit=999_999,
            used_today=0,
            remaining_today=999_999,
            usage_date=usage_date,
            is_active=True,
            granted_at=datetime.now(self._timezone),
            granted_via_token="admin",
        )

    def _usage_date(self) -> date:
        """Return the current quota date in the configured display timezone."""

        return datetime.now(self._timezone).date()

    def _get_lock(self) -> asyncio.Lock:
        """Create the lock lazily so sync construction works on Python 3.9."""

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
