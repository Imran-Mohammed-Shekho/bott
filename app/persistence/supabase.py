"""Async Postgres persistence suitable for Supabase-backed deployments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import asyncpg

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
