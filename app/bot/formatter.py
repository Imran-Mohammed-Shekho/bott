"""Telegram-friendly message formatting helpers."""

from typing import Iterable, List
from zoneinfo import ZoneInfo

from app.models.access import AccessTokenRecord, UserQuotaStatus
from app.models.signal import SignalLabel, SignalResponse, SubscriptionRecord
from app.models.trading import (
    AccountSummary,
    ClosePositionResponse,
    MarketOrderResponse,
    PositionSummary,
)
from app.services.signal_service import SignalService


def format_signal_message(
    signal: SignalResponse,
    display_timezone: str,
    broker_style: str,
) -> str:
    """Render a modern plain-text signal card for Telegram."""

    if broker_style == "pocket_option":
        return _format_pocket_option_signal_message(signal, display_timezone)

    return _format_generic_signal_message(signal, display_timezone)


def _format_generic_signal_message(signal: SignalResponse, display_timezone: str) -> str:
    """Render the generic forex-oriented signal layout."""

    local_time, utc_time = _format_times(signal.timestamp, display_timezone)
    lines = [
        f"╭─ 📊 {signal.display_pair}",
        "│",
        "├─ 🔔 ئاماژەکان",
        f"│  5s  ➜ {_format_signal_label(signal.signals['5s'].signal)}",
        f"│  10s ➜ {_format_signal_label(signal.signals['10s'].signal)}",
        f"│  30s ➜ {_format_signal_label(signal.signals['30s'].signal)}",
        f"│  1m  ➜ {_format_signal_label(signal.signals['1m'].signal)}",
        "│",
        "├─ 🎯 ئاستی متمانە",
        f"│  5s  ➜ {signal.signals['5s'].confidence:.2f}",
        f"│  10s ➜ {signal.signals['10s'].confidence:.2f}",
        f"│  30s ➜ {signal.signals['30s'].confidence:.2f}",
        f"│  1m  ➜ {signal.signals['1m'].confidence:.2f}",
        "│",
        "├─ 💹 وردەکاریی بازاڕ",
        f"│  نرخی ناوەڕاست: {_format_price(signal.pair, signal.current_mid_price)}",
        f"│  سپرێد: {_format_price(signal.pair, signal.spread)}",
        "│",
        "├─ 🕒 کات",
        f"│  ناوخۆ: {local_time}",
        f"│  UTC: {utc_time}",
        "│",
        "├─ ⚠️ ئاگاداری لە مەترسی",
        f"│  {signal.risk_warning}",
        "",
        f"╰─ ℹ️ {signal.disclaimer}",
    ]
    return "\n".join(lines)


def _format_pocket_option_signal_message(signal: SignalResponse, display_timezone: str) -> str:
    """Render a quick-trading style layout suitable for Pocket Option workflows."""

    local_time, utc_time = _format_times(signal.timestamp, display_timezone)
    lines = [
        f"╭─ ⚡ {signal.display_pair}",
        "│",
        "├─ 🎯 ئاراستە بۆ کاتی داخستن",
        f"│  5s  ➜ {_format_po_direction(signal.signals['5s'].signal)}",
        f"│  10s ➜ {_format_po_direction(signal.signals['10s'].signal)}",
        f"│  30s ➜ {_format_po_direction(signal.signals['30s'].signal)}",
        f"│  1m  ➜ {_format_po_direction(signal.signals['1m'].signal)}",
        "│",
        "├─ 📈 ئاستی متمانە",
        f"│  5s  ➜ {signal.signals['5s'].confidence:.2f}",
        f"│  10s ➜ {signal.signals['10s'].confidence:.2f}",
        f"│  30s ➜ {signal.signals['30s'].confidence:.2f}",
        f"│  1m  ➜ {signal.signals['1m'].confidence:.2f}",
        "│",
        "├─ 💹 وردەکاریی بازاڕ",
        f"│  نرخی ناوەڕاست: {_format_price(signal.pair, signal.current_mid_price)}",
        f"│  سپرێد: {_format_price(signal.pair, signal.spread)}",
        "│",
        "├─ 🕒 کاتی نیشاندراو",
        f"│  ناوخۆ: {local_time}",
        f"│  UTC: {utc_time}",
        "│",
        "├─ 🧭 تێبینیی بەکارهێنان",
        "│  بۆ هەمان ئەسێتی بازاڕی ڕاستەقینە بەکاریبهێنە، نەک OTC.",
        "│  ئەگەر ناوی ئەسێت یان کاتی داخستن جیاواز بوو، ئاماژەکە هاوتا نابێت.",
        "│",
        "├─ ⚠️ ئاگاداری لە مەترسی",
        f"│  {signal.risk_warning}",
        "",
        f"╰─ ℹ️ {signal.disclaimer}",
    ]
    return "\n".join(lines)


def format_help_message(default_interval_seconds: int) -> str:
    """Return the help text for the bot."""

    return "\n".join(
        [
            "✨ دەتوانیت دوگمەکانی خوارەوە یان فەرمانەکان بەکاربهێنیت.",
            "",
            "📚 فەرمانەکان:",
            "/start - ناساندنی بۆت",
            "/help - پیشاندانی ئەم یارمەتییە",
            "/pairs - لیستی جووتە پشتیوانی کراوەکان",
            "/signal EURUSD - وەرگرتنی دوایین ئاماژە",
            f"/watch EURUSD [{default_interval_seconds}] - چاودێریی دووبارە",
            "/stopwatch EURUSD - وەستاندنی نوێکردنەوەی جووتێک",
            "/status - پیشاندانی چاودێرییە چالاکەکان",
            "/redeem TOKEN - چالاککردنی چوونەژوورەوەی بۆت",
            "/quota - پیشاندانی سنووری داواکاریی ئەمڕۆ",
        ]
    )


def format_pairs(pairs: Iterable[str]) -> str:
    """Return a supported pairs message."""

    return "💱 جووتە پشتیوانی کراوەکان:\n" + "\n".join(
        f"- {SignalService.display_pair(pair)}" for pair in pairs
    )


def format_status(records: List[SubscriptionRecord]) -> str:
    """Return the current watch status for a chat."""

    if not records:
        return "📭 هیچ چاودێرییەکی چالاک نییە."

    lines = ["📡 چاودێرییە چالاکەکان:"]
    for record in records:
        lines.append(
            f"- {SignalService.display_pair(record.pair)} هەموو {record.interval_seconds} چرکە"
        )
    return "\n".join(lines)


def format_account_summary(summary: AccountSummary) -> str:
    """Render a broker account summary."""

    return "\n".join(
        [
            f"💼 ئەکاونت: {summary.account_id}",
            f"💵 Balance: {summary.balance:.2f} {summary.currency}",
            f"🧮 NAV: {summary.nav:.2f} {summary.currency}",
            f"📉 Unrealized P/L: {summary.unrealized_pnl:.2f}",
            f"🛡 Margin Available: {summary.margin_available:.2f}",
            f"📦 Margin Used: {summary.margin_used:.2f}",
            f"📍 Open Trades: {summary.open_trade_count}",
            f"📍 Open Positions: {summary.open_position_count}",
            f"⏳ Pending Orders: {summary.pending_order_count}",
        ]
    )


def format_positions(positions: List[PositionSummary]) -> str:
    """Render a broker position snapshot."""

    if not positions:
        return "📭 هیچ پۆزیشنی کراوە نییە."

    lines = ["📈 پۆزیشنی کراوەکان:"]
    for position in positions:
        lines.append(
            f"- {position.display_pair} | long={position.long.units:.0f} short={position.short.units:.0f} margin={position.margin_used:.2f}"
        )
    return "\n".join(lines)


def format_market_order_response(response: MarketOrderResponse) -> str:
    """Render an execution result."""

    fill_text = f"{response.fill_price:.5f}" if response.fill_price is not None else "-"
    return "\n".join(
        [
            f"✅ {response.status.upper()} | {response.display_pair}",
            f"Side: {response.side.value}",
            f"Units: {response.units}",
            f"Fill: {fill_text}",
            f"Mode: {response.mode.value}",
            f"Message: {response.message}",
        ]
    )


def format_close_position_response(response: ClosePositionResponse) -> str:
    """Render a close-position result."""

    pnl_text = f"{response.realized_pnl:.2f}" if response.realized_pnl is not None else "-"
    return "\n".join(
        [
            f"✅ {response.status.upper()} | {response.display_pair}",
            f"Side: {response.closed_side.value}",
            f"Units: {response.units}",
            f"Realized P/L: {pnl_text}",
            f"Mode: {response.mode.value}",
            f"Message: {response.message}",
        ]
    )


def format_access_token(record: AccessTokenRecord) -> str:
    """Render an admin-issued access token."""

    return "\n".join(
        [
            "🔐 New access token created",
            f"Token: {record.token}",
            f"Daily requests: {record.daily_limit}",
            "Share it with the user and tell them to run /redeem TOKEN",
        ]
    )


def format_quota_status(status: UserQuotaStatus, is_admin: bool = False) -> str:
    """Render the current per-day quota status for a single user."""

    if is_admin:
        return "\n".join(
            [
                "👑 Admin access",
                "Daily requests: unlimited",
                "Remaining today: unlimited",
            ]
        )

    username = f"@{status.username}" if status.username else "-"
    granted_via = status.granted_via_token or "direct"
    state = "active" if status.is_active else "disabled"
    return "\n".join(
        [
            f"🪪 User: {status.user_id}",
            f"Username: {username}",
            f"State: {state}",
            f"Daily requests: {status.daily_limit}",
            f"Used today: {status.used_today}",
            f"Remaining today: {status.remaining_today}",
            f"Granted via: {granted_via}",
        ]
    )


def format_user_quota_statuses(statuses: List[UserQuotaStatus]) -> str:
    """Render a compact admin overview of all granted users."""

    if not statuses:
        return "No managed users yet."

    lines = ["👥 Managed users:"]
    for status in statuses:
        username = f" @{status.username}" if status.username else ""
        state = "active" if status.is_active else "disabled"
        lines.append(
            f"- {status.user_id}{username} | {state} | {status.used_today}/{status.daily_limit} used | {status.remaining_today} left"
        )
    return "\n".join(lines)


def _format_signal_label(label: SignalLabel) -> str:
    """Translate signal labels for Telegram users."""

    mapping = {
        SignalLabel.BUY: "کڕین",
        SignalLabel.SELL: "فرۆشتن",
        SignalLabel.HOLD: "چاوەڕێ",
    }
    return mapping[label]


def _format_po_direction(label: SignalLabel) -> str:
    """Translate signal labels into quick-trading directions."""

    mapping = {
        SignalLabel.BUY: "🟢 سەرەوە",
        SignalLabel.SELL: "🔴 خوارەوە",
        SignalLabel.HOLD: "🟡 چاوەڕێ",
    }
    return mapping[label]


def _format_times(timestamp, display_timezone: str) -> tuple[str, str]:
    """Return human-friendly local and UTC timestamps."""

    local_zone = ZoneInfo(display_timezone)
    local_timestamp = timestamp.astimezone(local_zone)
    utc_timestamp = timestamp.astimezone(ZoneInfo("UTC"))

    local_text = local_timestamp.strftime("%Y-%m-%d %I:%M:%S %p")
    utc_text = utc_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{local_text} ({display_timezone})", utc_text


def _format_price(pair: str, value: float) -> str:
    """Format values using standard JPY and non-JPY precision."""

    decimals = 3 if pair.endswith("JPY") else 5
    return f"{value:.{decimals}f}"
