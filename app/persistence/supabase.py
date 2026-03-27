"""Async Postgres persistence suitable for Supabase-backed deployments."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import asyncpg

from app.models.access import AccessTokenRecord, UserAccessRecord
from app.models.execution import ExecutionConnectToken, UserExecutionProfile
from app.models.signal import SubscriptionRecord
from app.models.trading import OrderSide, TradeMode, TradeRecord


SCHEMA_SQL = (Path(__file__).resolve().parents[2] / "infra" / "supabase" / "schema.sql").read_text()


class SupabasePersistence:
    """Persist subscriptions and trade events to Postgres."""

    def __init__(
        self,
        database_url: str,
        pool_size: int,
        command_timeout_seconds: float,
    ):
        self._database_url = database_url
        self._pool_size = pool_size
        self._command_timeout_seconds = command_timeout_seconds
        self._pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        """Create a connection pool and ensure the schema exists."""

        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            dsn=self._database_url,
            min_size=1,
            max_size=self._pool_size,
            command_timeout=self._command_timeout_seconds,
            statement_cache_size=0,
            server_settings={"application_name": "forex-signals-bot"},
        )

        async with self._pool.acquire() as connection:
            await connection.execute(SCHEMA_SQL)

    async def close(self) -> None:
        """Close the connection pool."""

        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def upsert_subscription(self, record: SubscriptionRecord) -> SubscriptionRecord:
        """Store or replace a subscription."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                insert into bot_subscriptions (
                    chat_id,
                    user_id,
                    pair,
                    interval_seconds,
                    created_at
                )
                values ($1, $2, $3, $4, $5)
                on conflict (chat_id, pair) do update
                set user_id = excluded.user_id,
                    interval_seconds = excluded.interval_seconds,
                    created_at = excluded.created_at
                """,
                record.chat_id,
                record.user_id,
                record.pair,
                record.interval_seconds,
                record.created_at,
            )
        return record

    async def create_access_token(self, record: AccessTokenRecord) -> AccessTokenRecord:
        """Persist an admin-issued access token."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                insert into access_tokens (
                    token,
                    daily_limit,
                    issued_by,
                    issued_at,
                    redeemed_by,
                    redeemed_at,
                    is_active
                )
                values ($1, $2, $3, $4, $5, $6, $7)
                """,
                record.token,
                record.daily_limit,
                record.issued_by,
                record.issued_at,
                record.redeemed_by,
                record.redeemed_at,
                record.is_active,
            )
        return record

    async def redeem_access_token(
        self,
        token: str,
        user_id: int,
        username: Optional[str],
        redeemed_at: datetime,
    ) -> Optional[UserAccessRecord]:
        """Redeem a token and upsert the corresponding user grant atomically."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                token_row = await connection.fetchrow(
                    """
                    select *
                    from access_tokens
                    where token = $1
                    for update
                    """,
                    token,
                )
                if (
                    token_row is None
                    or not token_row["is_active"]
                    or token_row["redeemed_by"] is not None
                ):
                    return None

                access_row = await connection.fetchrow(
                    """
                    insert into bot_user_access (
                        user_id,
                        username,
                        daily_limit,
                        is_active,
                        granted_via_token,
                        granted_at,
                        updated_at
                    )
                    values ($1, $2, $3, true, $4, $5, $5)
                    on conflict (user_id) do update
                    set username = coalesce(excluded.username, bot_user_access.username),
                        daily_limit = excluded.daily_limit,
                        is_active = true,
                        granted_via_token = excluded.granted_via_token,
                        granted_at = excluded.granted_at,
                        updated_at = excluded.updated_at
                    returning *
                    """,
                    user_id,
                    username,
                    token_row["daily_limit"],
                    token,
                    redeemed_at,
                )
                await connection.execute(
                    """
                    update access_tokens
                    set redeemed_by = $2,
                        redeemed_at = $3,
                        is_active = false
                    where token = $1
                    """,
                    token,
                    user_id,
                    redeemed_at,
                )
        return self._user_access_from_row(access_row)

    async def upsert_user_access(self, record: UserAccessRecord) -> UserAccessRecord:
        """Create or update a direct user access grant."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                insert into bot_user_access (
                    user_id,
                    username,
                    daily_limit,
                    is_active,
                    granted_via_token,
                    granted_at,
                    updated_at
                )
                values ($1, $2, $3, $4, $5, $6, $6)
                on conflict (user_id) do update
                set username = coalesce(excluded.username, bot_user_access.username),
                    daily_limit = excluded.daily_limit,
                    is_active = excluded.is_active,
                    granted_via_token = excluded.granted_via_token,
                    granted_at = excluded.granted_at,
                    updated_at = excluded.updated_at
                returning *
                """,
                record.user_id,
                record.username,
                record.daily_limit,
                record.is_active,
                record.granted_via_token,
                record.granted_at,
            )
        return self._user_access_from_row(row)

    async def get_user_access(self, user_id: int) -> Optional[UserAccessRecord]:
        """Return the stored access grant for a user."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select user_id, username, daily_limit, is_active, granted_via_token, granted_at
                from bot_user_access
                where user_id = $1
                """,
                user_id,
            )
        if row is None:
            return None
        return self._user_access_from_row(row)

    async def list_user_access(self) -> List[UserAccessRecord]:
        """List all user access grants."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select user_id, username, daily_limit, is_active, granted_via_token, granted_at
                from bot_user_access
                order by granted_at desc, user_id asc
                """
            )
        return [self._user_access_from_row(row) for row in rows]

    async def set_user_active(self, user_id: int, is_active: bool) -> bool:
        """Toggle whether a user's access is active."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                update bot_user_access
                set is_active = $2,
                    updated_at = now()
                where user_id = $1
                """,
                user_id,
                is_active,
            )
        return result.endswith("1")

    async def get_daily_usage(self, user_id: int, usage_date: date) -> int:
        """Return the stored per-day request count for a user."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            count = await connection.fetchval(
                """
                select request_count
                from bot_user_daily_usage
                where user_id = $1 and usage_date = $2
                """,
                user_id,
                usage_date,
            )
        return int(count or 0)

    async def increment_daily_usage(self, user_id: int, usage_date: date, amount: int = 1) -> int:
        """Atomically increment and return the per-day request count for a user."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                insert into bot_user_daily_usage (user_id, usage_date, request_count)
                values ($1, $2, $3)
                on conflict (user_id, usage_date) do update
                set request_count = bot_user_daily_usage.request_count + excluded.request_count
                returning request_count
                """,
                user_id,
                usage_date,
                amount,
            )
        return int(row["request_count"])

    async def create_execution_connect_token(
        self,
        record: ExecutionConnectToken,
    ) -> ExecutionConnectToken:
        """Persist a one-time connect token."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                insert into execution_connect_tokens (
                    token,
                    user_id,
                    created_at,
                    expires_at,
                    used_at,
                    is_active
                )
                values ($1, $2, $3, $4, $5, $6)
                """,
                record.token,
                record.user_id,
                record.created_at,
                record.expires_at,
                record.used_at,
                record.is_active,
            )
        return record

    async def consume_execution_connect_token(
        self,
        token: str,
        consumed_at: datetime,
    ) -> Optional[ExecutionConnectToken]:
        """Consume a one-time connect token if it is still valid."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    select *
                    from execution_connect_tokens
                    where token = $1
                    for update
                    """,
                    token,
                )
                if (
                    row is None
                    or not row["is_active"]
                    or row["used_at"] is not None
                    or row["expires_at"] < consumed_at
                ):
                    return None

                await connection.execute(
                    """
                    update execution_connect_tokens
                    set used_at = $2,
                        is_active = false
                    where token = $1
                    """,
                    token,
                    consumed_at,
                )

        return self._execution_connect_token_from_row(
            row,
            used_at=consumed_at,
            is_active=False,
        )

    async def get_execution_connect_token(self, token: str) -> Optional[ExecutionConnectToken]:
        """Return a connect token by value."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from execution_connect_tokens
                where token = $1
                """,
                token,
            )
        if row is None:
            return None
        return self._execution_connect_token_from_row(row)

    async def upsert_user_execution_profile(
        self,
        record: UserExecutionProfile,
    ) -> UserExecutionProfile:
        """Create or update a user's stored execution profile."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                insert into user_execution_profiles (
                    user_id,
                    provider,
                    encrypted_session,
                    autotrade_enabled,
                    trade_amount,
                    expiration_label,
                    signal_horizon,
                    created_at,
                    updated_at
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                on conflict (user_id) do update
                set provider = excluded.provider,
                    encrypted_session = excluded.encrypted_session,
                    autotrade_enabled = excluded.autotrade_enabled,
                    trade_amount = excluded.trade_amount,
                    expiration_label = excluded.expiration_label,
                    signal_horizon = excluded.signal_horizon,
                    updated_at = excluded.updated_at
                returning *
                """,
                record.user_id,
                record.provider,
                record.encrypted_session,
                record.autotrade_enabled,
                record.trade_amount,
                record.expiration_label,
                record.signal_horizon,
                record.created_at,
                record.updated_at,
            )
        return self._user_execution_profile_from_row(row)

    async def get_user_execution_profile(self, user_id: int) -> Optional[UserExecutionProfile]:
        """Return a user's stored execution profile."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from user_execution_profiles
                where user_id = $1
                """,
                user_id,
            )
        if row is None:
            return None
        return self._user_execution_profile_from_row(row)

    async def delete_user_execution_profile(self, user_id: int) -> bool:
        """Delete a user's stored execution profile."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                delete from user_execution_profiles
                where user_id = $1
                """,
                user_id,
            )
        return result.endswith("1")

    async def remove_subscription(self, chat_id: int, pair: str) -> bool:
        """Delete a subscription."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                "delete from bot_subscriptions where chat_id = $1 and pair = $2",
                chat_id,
                pair,
            )
        return result.endswith("1")

    async def list_subscriptions(self, chat_id: Optional[int] = None) -> List[SubscriptionRecord]:
        """List subscriptions, optionally filtered to a chat."""

        pool = self._require_pool()
        query = """
            select chat_id, user_id, pair, interval_seconds, created_at
            from bot_subscriptions
        """
        params: List[object] = []
        if chat_id is not None:
            query += " where chat_id = $1"
            params.append(chat_id)
        query += " order by chat_id asc, pair asc"

        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
        return [
            SubscriptionRecord(
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                pair=row["pair"],
                interval_seconds=row["interval_seconds"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def record_trade(self, record: TradeRecord) -> TradeRecord:
        """Insert a trade log record."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                insert into trade_records (
                    id,
                    mode,
                    pair,
                    side,
                    action,
                    units,
                    status,
                    fill_price,
                    realized_pnl,
                    external_order_id,
                    external_trade_id,
                    account_id,
                    request_source,
                    requested_by,
                    error_message,
                    request_payload,
                    response_payload,
                    created_at,
                    closed_at
                )
                values (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16::jsonb, $17::jsonb, $18, $19
                )
                """,
                record.id,
                record.mode.value,
                record.pair,
                record.side.value if isinstance(record.side, OrderSide) else record.side,
                record.action,
                record.units,
                record.status,
                record.fill_price,
                record.realized_pnl,
                record.external_order_id,
                record.external_trade_id,
                record.account_id,
                record.request_source,
                record.requested_by,
                record.error_message,
                json.dumps(record.request_payload),
                json.dumps(record.response_payload),
                record.created_at,
                record.closed_at,
            )
        return record

    async def list_recent_trades(self, limit: int = 20) -> List[TradeRecord]:
        """Return the most recent trade log entries."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select *
                from trade_records
                order by created_at desc
                limit $1
                """,
                limit,
            )
        return [self._trade_record_from_row(row) for row in rows]

    async def get_daily_realized_pnl(self, mode: TradeMode) -> float:
        """Return today's realized PnL for the selected mode."""

        pool = self._require_pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                """
                select coalesce(sum(realized_pnl), 0.0)
                from trade_records
                where mode = $1
                  and coalesce(closed_at, created_at) >= date_trunc('day', now())
                """,
                mode.value,
            )
        return float(value or 0.0)

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Supabase persistence is not initialized.")
        return self._pool

    @staticmethod
    def _trade_record_from_row(row: asyncpg.Record) -> TradeRecord:
        return TradeRecord(
            id=row["id"],
            mode=TradeMode(row["mode"]),
            pair=row["pair"],
            side=row["side"],
            action=row["action"],
            units=row["units"],
            status=row["status"],
            fill_price=row["fill_price"],
            realized_pnl=row["realized_pnl"],
            external_order_id=row["external_order_id"],
            external_trade_id=row["external_trade_id"],
            account_id=row["account_id"],
            request_source=row["request_source"],
            requested_by=row["requested_by"],
            error_message=row["error_message"],
            request_payload=dict(row["request_payload"] or {}),
            response_payload=dict(row["response_payload"] or {}),
            created_at=row["created_at"],
            closed_at=row["closed_at"],
        )

    @staticmethod
    def _user_access_from_row(row: asyncpg.Record) -> UserAccessRecord:
        return UserAccessRecord(
            user_id=row["user_id"],
            username=row["username"],
            daily_limit=row["daily_limit"],
            is_active=row["is_active"],
            granted_via_token=row["granted_via_token"],
            granted_at=row["granted_at"],
        )

    @staticmethod
    def _execution_connect_token_from_row(
        row: asyncpg.Record,
        *,
        used_at: Optional[datetime] = None,
        is_active: Optional[bool] = None,
    ) -> ExecutionConnectToken:
        return ExecutionConnectToken(
            token=row["token"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            used_at=row["used_at"] if used_at is None else used_at,
            is_active=row["is_active"] if is_active is None else is_active,
        )

    @staticmethod
    def _user_execution_profile_from_row(row: asyncpg.Record) -> UserExecutionProfile:
        return UserExecutionProfile(
            user_id=row["user_id"],
            provider=row["provider"],
            encrypted_session=row["encrypted_session"],
            autotrade_enabled=row["autotrade_enabled"],
            trade_amount=row["trade_amount"],
            expiration_label=row["expiration_label"],
            signal_horizon=row["signal_horizon"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
