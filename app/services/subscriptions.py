"""In-memory subscription management for watch alerts."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.models.signal import SubscriptionRecord
from app.persistence.supabase import SupabasePersistence


class SubscriptionService:
    """Track active pair subscriptions in memory."""

    def __init__(self, persistence: Optional[SupabasePersistence] = None):
        self._subscriptions: Dict[Tuple[int, str], SubscriptionRecord] = {}
        self._lock: Optional[asyncio.Lock] = None
        self._persistence = persistence

    async def upsert(
        self,
        chat_id: int,
        user_id: int,
        pair: str,
        interval_seconds: int,
    ) -> SubscriptionRecord:
        """Create or replace a subscription."""

        record = SubscriptionRecord(
            chat_id=chat_id,
            user_id=user_id,
            pair=pair,
            interval_seconds=interval_seconds,
            created_at=datetime.now(timezone.utc),
        )
        if self._persistence is not None:
            return await self._persistence.upsert_subscription(record)
        async with self._get_lock():
            self._subscriptions[(chat_id, pair)] = record
        return record

    async def remove(self, chat_id: int, pair: str) -> bool:
        """Delete a subscription if present."""

        if self._persistence is not None:
            return await self._persistence.remove_subscription(chat_id, pair)
        async with self._get_lock():
            return self._subscriptions.pop((chat_id, pair), None) is not None

    async def list_for_chat(self, chat_id: int) -> List[SubscriptionRecord]:
        """List active subscriptions for a chat."""

        if self._persistence is not None:
            return await self._persistence.list_subscriptions(chat_id)
        async with self._get_lock():
            records = [
                record
                for (subscription_chat_id, _pair), record in self._subscriptions.items()
                if subscription_chat_id == chat_id
            ]
        return sorted(records, key=lambda record: record.pair)

    async def list_all(self) -> List[SubscriptionRecord]:
        """List every active subscription."""

        if self._persistence is not None:
            return await self._persistence.list_subscriptions(chat_id=None)
        async with self._get_lock():
            records = list(self._subscriptions.values())
        return sorted(records, key=lambda record: (record.chat_id, record.pair))

    def _get_lock(self) -> asyncio.Lock:
        """Create the lock lazily so sync construction works on Python 3.9."""

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
