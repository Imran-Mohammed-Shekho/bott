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

create table if not exists access_tokens (
    token text primary key,
    daily_limit integer not null check (daily_limit > 0),
    issued_by bigint not null,
    issued_at timestamptz not null default now(),
    redeemed_by bigint unique,
    redeemed_at timestamptz,
    is_active boolean not null default true
);

create table if not exists bot_user_access (
    user_id bigint primary key,
    username text,
    daily_limit integer not null check (daily_limit > 0),
    is_active boolean not null default true,
    granted_via_token text references access_tokens(token) on delete set null,
    granted_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists bot_user_daily_usage (
    user_id bigint not null references bot_user_access(user_id) on delete cascade,
    usage_date date not null,
    request_count integer not null default 0,
    primary key (user_id, usage_date)
);

create index if not exists idx_bot_user_daily_usage_date on bot_user_daily_usage (usage_date desc);

create table if not exists execution_connect_tokens (
    token text primary key,
    user_id bigint not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz,
    is_active boolean not null default true
);

create index if not exists idx_execution_connect_tokens_user_id
    on execution_connect_tokens (user_id, expires_at desc);

create table if not exists user_execution_profiles (
    user_id bigint primary key,
    provider text not null,
    encrypted_session text not null,
    autotrade_enabled boolean not null default false,
    trade_amount integer not null check (trade_amount > 0),
    expiration_label text not null default 'M5',
    signal_horizon text not null default '1m',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
