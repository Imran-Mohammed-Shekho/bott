create table if not exists bot_subscriptions (
    chat_id bigint not null,
    user_id bigint,
    pair text not null,
    interval_seconds integer not null,
    created_at timestamptz not null default now(),
    primary key (chat_id, pair)
);

create table if not exists trade_records (
    id text primary key,
    mode text not null,
    pair text not null,
    side text,
    action text not null,
    units text not null,
    status text not null,
    fill_price double precision,
    realized_pnl double precision,
    external_order_id text,
    external_trade_id text,
    account_id text,
    request_source text not null,
    requested_by text,
    error_message text,
    request_payload jsonb not null default '{}'::jsonb,
    response_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    closed_at timestamptz
);

create index if not exists idx_trade_records_created_at on trade_records (created_at desc);
create index if not exists idx_trade_records_pair on trade_records (pair);
