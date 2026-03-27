"""Telegram command handlers and scheduled alert jobs."""

import json
import logging
from typing import Optional

from telegram import CallbackQuery, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bootstrap import AppContext
from app.bot.formatter import (
    format_access_token,
    format_account_summary,
    format_close_position_response,
    format_execution_profile,
    format_help_message,
    format_market_order_response,
    format_pairs,
    format_positions,
    format_quota_status,
    format_signal_message,
    format_status,
    format_user_quota_statuses,
)
from app.bot.keyboards import (
    MAIN_MENU_HELP,
    MAIN_MENU_PAIRS,
    MAIN_MENU_SIGNAL,
    MAIN_MENU_STATUS,
    MAIN_MENU_STOP,
    MAIN_MENU_WATCH,
    build_main_menu_keyboard,
    build_signal_pair_keyboard,
    build_stop_watch_keyboard,
    build_watch_interval_keyboard,
    build_watch_pair_keyboard,
)
from app.services.access_control import AccessDeniedError, QuotaExceededError
from app.models.trading import ClosePositionRequest, MarketOrderRequest, OrderSide, PositionCloseSide
from app.models.signal import SignalLabel

logger = logging.getLogger(__name__)


def build_telegram_application(app_context: AppContext) -> Application:
    """Create and configure the Telegram application."""

    token = app_context.settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")

    application = Application.builder().token(token).build()
    application.bot_data["app_context"] = app_context

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pairs", pairs_command))
    application.add_handler(CommandHandler("signal", signal_command))
    application.add_handler(CommandHandler("watch", watch_command))
    application.add_handler(CommandHandler("stopwatch", stopwatch_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("connectsession", connectsession_command))
    application.add_handler(CommandHandler("savesession", savesession_command))
    application.add_handler(CommandHandler("cancelsession", cancelsession_command))
    application.add_handler(CommandHandler("disconnectsession", disconnectsession_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("autotrade", autotrade_command))
    application.add_handler(CommandHandler("amount", amount_command))
    application.add_handler(CommandHandler("expiry", expiry_command))
    application.add_handler(CommandHandler("horizon", horizon_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("quota", quota_command))
    application.add_handler(CommandHandler("grant", grant_command))
    application.add_handler(CommandHandler("setquota", setquota_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("disableuser", disableuser_command))
    application.add_handler(CommandHandler("account", account_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("execsignal", execsignal_command))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("sell", sell_command))
    application.add_handler(CommandHandler("close", close_position_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message_handler))
    application.add_error_handler(error_handler)

    if application.job_queue is None:
        raise RuntimeError("Job queue is unavailable. Install python-telegram-bot[job-queue].")

    return application


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start."""

    app_context = _app_context(context)
    text = (
        f"{app_context.settings.app_name} ئامادەیە.\n"
        "لە مێنیوی خوارەوە جووتێک هەڵبژێرە، ئاماژە داوا بکە، چاودێری دەست پێ بکە یان بیوەستێنە."
    )
    await _reply(update, text, reply_markup=build_main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""

    app_context = _app_context(context)
    message = format_help_message(app_context.settings.default_watch_interval_seconds)
    if _is_admin(update, app_context):
        message += (
            "\n/grant 20 - generate onboarding token"
            "\n/setquota 123456789 20 - set direct daily quota"
            "\n/users - list managed users"
            "\n/disableuser 123456789 - disable bot access"
            "\n/account - account summary"
            "\n/positions - open positions"
            "\n/execsignal EURUSD [1m] [1] - trade current signal"
            "\n/buy EURUSD 100"
            "\n/sell EURUSD 100"
            "\n/close EURUSD [all|long|short]"
        )
    await _reply(update, message, reply_markup=build_main_menu_keyboard())


async def pairs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pairs."""

    app_context = _app_context(context)
    await _reply(
        update,
        format_pairs(app_context.signal_service.list_pairs()),
        reply_markup=build_main_menu_keyboard(),
    )


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /signal <pair>."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    pair = _required_pair_arg(context)
    if not pair:
        await _reply(
            update,
            "جووتێک هەڵبژێرە بۆ ئاماژەیەکی یەکجار.",
            reply_markup=build_signal_pair_keyboard(app_context.signal_service.list_pairs()),
        )
        return

    try:
        await app_context.access_control_service.ensure_can_request(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
        )
        signal = await app_context.signal_service.get_signal(pair)
        await app_context.access_control_service.consume_request(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
        )
    except (AccessDeniedError, QuotaExceededError) as exc:
        await _reply(update, _access_error_message(exc))
        return
    except ValueError as exc:
        await _reply(update, str(exc))
        return
    except Exception:
        logger.exception("Signal command failed")
        await _reply(update, "دروستکردنی ئاماژە سەرکەوتوو نەبوو. دواتر هەوڵبدەرەوە.")
        return

    await _reply(
        update,
        format_signal_message(
            signal,
            app_context.settings.display_timezone,
            app_context.settings.broker_style,
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watch <pair> [interval]."""

    app_context = _app_context(context)
    if update.effective_chat is None or update.effective_user is None:
        return

    pair_arg = _required_pair_arg(context)
    if not pair_arg:
        await _reply(
            update,
            "جووتێک هەڵبژێرە بۆ چاودێری.",
            reply_markup=build_watch_pair_keyboard(app_context.signal_service.list_pairs()),
        )
        return

    interval_seconds = app_context.settings.default_watch_interval_seconds
    if len(context.args) >= 2:
        try:
            interval_seconds = int(context.args[1])
        except ValueError:
            await _reply(update, "ماوەکە دەبێت ژمارەیەکی تەواوی چرکە بێت.")
            return

    if interval_seconds < app_context.settings.min_watch_interval_seconds:
        await _reply(
            update,
            f"ماوەکە دەبێت لانیکەم {app_context.settings.min_watch_interval_seconds} چرکە بێت.",
        )
        return
    if interval_seconds > app_context.settings.max_watch_interval_seconds:
        await _reply(
            update,
            f"ماوەکە نابێت زیاتر بێت لە {app_context.settings.max_watch_interval_seconds} چرکە.",
        )
        return

    try:
        pair = app_context.signal_service.resolve_pair(pair_arg)
        await app_context.access_control_service.ensure_can_request(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
        )
        signal = await app_context.signal_service.get_signal(pair)
        await app_context.access_control_service.consume_request(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
        )
    except (AccessDeniedError, QuotaExceededError) as exc:
        await _reply(update, _access_error_message(exc))
        return
    except ValueError as exc:
        await _reply(update, str(exc))
        return
    except Exception:
        logger.exception("Watch command failed")
        await _reply(update, "دەستپێکردنی چاودێری سەرکەوتوو نەبوو. دواتر هەوڵبدەرەوە.")
        return

    await app_context.subscription_service.upsert(
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        pair=pair,
        interval_seconds=interval_seconds,
    )
    _schedule_watch_job(
        context.application,
        update.effective_chat.id,
        update.effective_user.id,
        pair,
        interval_seconds,
    )

    await _reply(
        update,
        f"{app_context.signal_service.display_pair(pair)} هەموو {interval_seconds} چرکە چاودێری دەکرێت.",
        reply_markup=build_main_menu_keyboard(),
    )
    await _reply(
        update,
        format_signal_message(
            signal,
            app_context.settings.display_timezone,
            app_context.settings.broker_style,
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def stopwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stopwatch <pair>."""

    app_context = _app_context(context)
    if update.effective_chat is None:
        return

    pair_arg = _required_pair_arg(context)
    if not pair_arg:
        records = await app_context.subscription_service.list_for_chat(update.effective_chat.id)
        if not records:
            await _reply(update, "هیچ چاودێرییەکی چالاک بۆ ئەو جووتە نەدۆزرایەوە.", reply_markup=build_main_menu_keyboard())
            return
        await _reply(
            update,
            "ئەو چاودێرییە هەڵبژێرە کە دەتەوێت بیوەستێنیت.",
            reply_markup=build_stop_watch_keyboard(records),
        )
        return

    try:
        pair = app_context.signal_service.normalize_pair(pair_arg)
    except ValueError as exc:
        await _reply(update, str(exc))
        return

    job_name = _job_name(update.effective_chat.id, pair)
    removed_job = False
    for job in context.job_queue.get_jobs_by_name(job_name):
        removed_job = True
        job.schedule_removal()

    removed_record = await app_context.subscription_service.remove(update.effective_chat.id, pair)
    if removed_job or removed_record:
        await _reply(
            update,
            f"نوێکردنەوەکان بۆ {app_context.signal_service.display_pair(pair)} وەستان.",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    await _reply(update, "هیچ چاودێرییەکی چالاک بۆ ئەو جووتە نەدۆزرایەوە.", reply_markup=build_main_menu_keyboard())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status."""

    app_context = _app_context(context)
    if update.effective_chat is None:
        return

    records = await app_context.subscription_service.list_for_chat(update.effective_chat.id)
    await _reply(update, format_status(records), reply_markup=build_main_menu_keyboard())


async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /connect by issuing a one-time secure session link."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return

    try:
        token = await app_context.execution_profile_service.issue_connect_token(
            update.effective_user.id
        )
        connect_url = app_context.execution_profile_service.build_connect_url(token.token)
    except RuntimeError as exc:
        await _reply(update, str(exc), reply_markup=build_main_menu_keyboard())
        return

    await _reply(
        update,
        "\n".join(
            [
                "Open this secure link to connect your Pocket Option session:",
                f"{connect_url}",
                "If you want the easy flow, run scripts/connect_pocket_option_session.py with this URL.",
                f"Link expires in {app_context.settings.connect_token_ttl_minutes} minutes.",
            ]
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def connectsession_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /connectsession and enable JSON capture mode in chat."""

    if update.effective_user is None:
        return

    context.user_data["session_capture"] = {
        "chunks": [],
        "started_by": update.effective_user.id,
    }
    await _reply(
        update,
        "\n".join(
            [
                "Session capture mode is on.",
                "Paste your full Pocket Option storageState JSON in one or more messages.",
                "When you finish, send /savesession",
                "To abort, send /cancelsession",
            ]
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def savesession_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /savesession and encrypt the pasted session JSON."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return

    capture_state = context.user_data.get("session_capture")
    if not capture_state or not capture_state.get("chunks"):
        await _reply(update, "No session JSON captured yet. Use /connectsession first.")
        return

    payload = "\n".join(capture_state["chunks"])
    try:
        json.loads(payload)
        status = await app_context.execution_profile_service.save_session_json(
            user_id=update.effective_user.id,
            storage_state_json=payload,
        )
    except Exception as exc:
        await _reply(update, f"Session save failed: {exc}")
        return

    context.user_data.pop("session_capture", None)
    await _reply(
        update,
        "Session stored securely.\n\n" + format_execution_profile(status),
        reply_markup=build_main_menu_keyboard(),
    )


async def cancelsession_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancelsession."""

    context.user_data.pop("session_capture", None)
    await _reply(update, "Session capture cancelled.", reply_markup=build_main_menu_keyboard())


async def disconnectsession_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /disconnectsession."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return

    removed = await app_context.execution_profile_service.disconnect_profile(update.effective_user.id)
    context.user_data.pop("session_capture", None)
    if not removed:
        await _reply(update, "No stored execution session found.", reply_markup=build_main_menu_keyboard())
        return

    await _reply(update, "Stored execution session removed.", reply_markup=build_main_menu_keyboard())


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profile for the sender's execution profile."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return

    status = await app_context.execution_profile_service.get_profile_status(update.effective_user.id)
    if status is None:
        await _reply(
            update,
            "No execution profile connected yet. Use /connect first.",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    await _reply(update, format_execution_profile(status), reply_markup=build_main_menu_keyboard())


async def autotrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /autotrade on|off."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /autotrade on|off")
        return

    enabled = context.args[0].strip().lower()
    if enabled not in {"on", "off"}:
        await _reply(update, "Usage: /autotrade on|off")
        return

    try:
        status = await app_context.execution_profile_service.set_autotrade(
            update.effective_user.id,
            enabled == "on",
        )
    except RuntimeError as exc:
        await _reply(update, str(exc))
        return

    await _reply(update, format_execution_profile(status), reply_markup=build_main_menu_keyboard())


async def amount_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /amount <value>."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /amount 1")
        return

    try:
        amount = int(context.args[0])
        status = await app_context.execution_profile_service.set_trade_amount(
            update.effective_user.id,
            amount,
        )
    except (RuntimeError, ValueError) as exc:
        await _reply(update, str(exc))
        return

    await _reply(update, format_execution_profile(status), reply_markup=build_main_menu_keyboard())


async def expiry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /expiry <label>."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /expiry M5")
        return

    try:
        status = await app_context.execution_profile_service.set_expiration_label(
            update.effective_user.id,
            context.args[0],
        )
    except (RuntimeError, ValueError) as exc:
        await _reply(update, str(exc))
        return

    await _reply(update, format_execution_profile(status), reply_markup=build_main_menu_keyboard())


async def horizon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /horizon <5s|10s|30s|1m>."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /horizon 1m")
        return

    try:
        status = await app_context.execution_profile_service.set_signal_horizon(
            update.effective_user.id,
            context.args[0],
        )
    except (RuntimeError, ValueError) as exc:
        await _reply(update, str(exc))
        return

    await _reply(update, format_execution_profile(status), reply_markup=build_main_menu_keyboard())


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /redeem <token>."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /redeem ACCESS_TOKEN", reply_markup=build_main_menu_keyboard())
        return

    try:
        status = await app_context.access_control_service.redeem_token(
            token=context.args[0],
            user_id=update.effective_user.id,
            username=update.effective_user.username,
        )
    except AccessDeniedError as exc:
        await _reply(update, str(exc), reply_markup=build_main_menu_keyboard())
        return

    await _reply(
        update,
        "Access activated.\n\n" + format_quota_status(status),
        reply_markup=build_main_menu_keyboard(),
    )


async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /quota."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return

    status = await app_context.access_control_service.get_user_status(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
    )
    if status is None:
        await _reply(
            update,
            "No access is active for your account yet. Ask admin for a token and use /redeem TOKEN.",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    await _reply(
        update,
        format_quota_status(status, is_admin=_is_admin(update, app_context)),
        reply_markup=build_main_menu_keyboard(),
    )


async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /grant <daily_limit> for admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to manage access.")
        return
    if update.effective_user is None:
        return
    if not context.args:
        await _reply(update, "Usage: /grant 20")
        return

    try:
        daily_limit = int(context.args[0])
    except ValueError:
        await _reply(update, "Daily limit must be an integer.")
        return

    try:
        record = await app_context.access_control_service.issue_token(
            daily_limit=daily_limit,
            issued_by=update.effective_user.id,
        )
    except ValueError as exc:
        await _reply(update, str(exc))
        return

    await _reply(update, format_access_token(record), reply_markup=build_main_menu_keyboard())


async def setquota_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setquota <user_id> <daily_limit> for admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to manage access.")
        return
    if len(context.args) < 2:
        await _reply(update, "Usage: /setquota 123456789 20")
        return

    try:
        user_id = int(context.args[0])
        daily_limit = int(context.args[1])
    except ValueError:
        await _reply(update, "User ID and daily limit must be integers.")
        return

    try:
        status = await app_context.access_control_service.set_user_quota(
            user_id=user_id,
            daily_limit=daily_limit,
        )
    except ValueError as exc:
        await _reply(update, str(exc))
        return

    await _reply(
        update,
        "User quota updated.\n\n" + format_quota_status(status),
        reply_markup=build_main_menu_keyboard(),
    )


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /users for admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to manage access.")
        return

    statuses = await app_context.access_control_service.list_user_statuses()
    await _reply(update, format_user_quota_statuses(statuses), reply_markup=build_main_menu_keyboard())


async def disableuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /disableuser <user_id> for admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to manage access.")
        return
    if not context.args:
        await _reply(update, "Usage: /disableuser 123456789")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await _reply(update, "User ID must be an integer.")
        return

    disabled = await app_context.access_control_service.deactivate_user(user_id)
    if not disabled:
        await _reply(update, "No managed user found with that ID.", reply_markup=build_main_menu_keyboard())
        return

    await _reply(
        update,
        f"User {user_id} has been disabled.",
        reply_markup=build_main_menu_keyboard(),
    )


async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /account for bot admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to use trading commands.")
        return
    try:
        summary = await app_context.trading_service.get_account_summary()
    except Exception as exc:
        logger.exception("Account command failed")
        await _reply(update, str(exc))
        return
    await _reply(update, format_account_summary(summary), reply_markup=build_main_menu_keyboard())


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /positions for bot admins."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to use trading commands.")
        return
    try:
        positions = await app_context.trading_service.list_open_positions()
    except Exception as exc:
        logger.exception("Positions command failed")
        await _reply(update, str(exc))
        return
    await _reply(update, format_positions(positions), reply_markup=build_main_menu_keyboard())


async def execsignal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /execsignal <pair> [horizon] [amount]."""

    app_context = _app_context(context)
    if update.effective_user is None:
        return
    profile = await app_context.execution_profile_service.get_profile_status(update.effective_user.id)
    if not _is_admin(update, app_context) and profile is None:
        await _reply(update, "No execution profile connected yet. Use /connect first.")
        return
    if not context.args:
        await _reply(update, "Usage: /execsignal EURUSD [1m] [1]")
        return

    pair_arg = context.args[0]
    horizon = context.args[1] if len(context.args) >= 2 else "1m"
    if horizon not in {"5s", "10s", "30s", "1m"}:
        await _reply(update, "Horizon must be one of: 5s, 10s, 30s, 1m.")
        return

    try:
        amount = int(context.args[2]) if len(context.args) >= 3 else (
            profile.trade_amount if profile is not None else app_context.settings.pocket_option_trade_amount
        )
    except ValueError:
        await _reply(update, "Amount must be an integer.")
        return

    try:
        signal = await app_context.signal_service.get_signal(pair_arg)
    except Exception as exc:
        logger.exception("Signal execution command failed while generating signal")
        await _reply(update, str(exc))
        return

    selected = signal.signals[horizon]
    if selected.signal == SignalLabel.HOLD:
        await _reply(
            update,
            f"No trade opened. Current {horizon} signal for {signal.display_pair} is HOLD.",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    side = OrderSide.BUY if selected.signal == SignalLabel.BUY else OrderSide.SELL
    try:
        response = await app_context.trading_service.place_market_order(
            MarketOrderRequest(
                pair=signal.pair,
                side=side,
                units=amount,
                request_source="telegram_execsignal",
                requested_by=str(update.effective_user.id),
            )
        )
    except Exception as exc:
        logger.exception("Signal execution command failed while placing order")
        await _reply(update, str(exc))
        return

    await _reply(
        update,
        "\n".join(
            [
                f"Signal selected: {signal.display_pair} {horizon} {selected.signal.value} ({selected.confidence:.2f})",
                format_market_order_response(response),
            ]
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /buy <pair> <units>."""

    await _place_market_order(update, context, side=OrderSide.BUY)


async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sell <pair> <units>."""

    await _place_market_order(update, context, side=OrderSide.SELL)


async def close_position_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /close <pair> [all|long|short]."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to use trading commands.")
        return
    if not context.args:
        await _reply(update, "Usage: /close EURUSD [all|long|short]")
        return

    pair = context.args[0]
    close_side = PositionCloseSide.ALL
    if len(context.args) >= 2:
        try:
            close_side = PositionCloseSide(context.args[1].lower())
        except ValueError:
            await _reply(update, "Close side must be one of: all, long, short.")
            return

    try:
        response = await app_context.trading_service.close_position(
            pair=pair,
            request=ClosePositionRequest(side=close_side),
            request_source="telegram",
            requested_by=str(update.effective_user.id) if update.effective_user else None,
        )
    except Exception as exc:
        logger.exception("Close position command failed")
        await _reply(update, str(exc))
        return

    await _reply(
        update,
        format_close_position_response(response),
        reply_markup=build_main_menu_keyboard(),
    )


async def menu_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses from the persistent reply keyboard."""

    if update.effective_message is None or update.effective_chat is None:
        return

    app_context = _app_context(context)
    text = (update.effective_message.text or "").strip()
    capture_state = context.user_data.get("session_capture")

    if capture_state is not None:
        chunks = capture_state.setdefault("chunks", [])
        chunks.append(text)
        await _reply(
            update,
            f"Captured session chunk {len(chunks)}. Send more JSON or use /savesession.",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    if text == MAIN_MENU_SIGNAL:
        await _reply(
            update,
            "جووتێک هەڵبژێرە بۆ ئاماژەیەکی یەکجار.",
            reply_markup=build_signal_pair_keyboard(app_context.signal_service.list_pairs()),
        )
        return

    if text == MAIN_MENU_WATCH:
        await _reply(
            update,
            "جووتێک هەڵبژێرە بۆ چاودێری.",
            reply_markup=build_watch_pair_keyboard(app_context.signal_service.list_pairs()),
        )
        return

    if text == MAIN_MENU_STOP:
        records = await app_context.subscription_service.list_for_chat(update.effective_chat.id)
        if not records:
            await _reply(update, "هیچ چاودێرییەکی چالاک بۆ وەستاندن نییە.", reply_markup=build_main_menu_keyboard())
            return
        await _reply(
            update,
            "ئەو چاودێرییە هەڵبژێرە کە دەتەوێت بیوەستێنیت.",
            reply_markup=build_stop_watch_keyboard(records),
        )
        return

    if text == MAIN_MENU_STATUS:
        await status_command(update, context)
        return

    if text == MAIN_MENU_PAIRS:
        await pairs_command(update, context)
        return

    if text == MAIN_MENU_HELP:
        await help_command(update, context)
        return

    await _reply(
        update,
        "دوگمەکانی مێنیوی خوارەوە بەکاربهێنە بۆ بەکارهێنانی بۆت.",
        reply_markup=build_main_menu_keyboard(),
    )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callbacks for pairs and watch controls."""

    if update.callback_query is None:
        return

    query = update.callback_query
    app_context = _app_context(context)
    await query.answer()

    data = query.data or ""
    if data == "menu:cancel":
        await query.edit_message_text("کردارەکە هەڵوەشایەوە.")
        if update.effective_chat is not None:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="مێنیوی سەرەکی ئامادەیە.",
                reply_markup=build_main_menu_keyboard(),
            )
        return

    if data.startswith("signal:"):
        pair = data.split(":", 1)[1]
        await _send_signal_from_callback(query, context, app_context, pair)
        return

    if data.startswith("watchpair:"):
        pair = data.split(":", 1)[1]
        await query.edit_message_text(
            text=f"ماوەیەک هەڵبژێرە بۆ {app_context.signal_service.display_pair(pair)}.",
            reply_markup=build_watch_interval_keyboard(pair),
        )
        return

    if data.startswith("watchstart:"):
        _prefix, pair, interval_text = data.split(":")
        await _start_watch_from_callback(query, context, app_context, pair, int(interval_text))
        return

    if data.startswith("stop:"):
        pair = data.split(":", 1)[1]
        await _stop_watch_from_callback(query, context, app_context, pair)
        return


async def watch_job_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send scheduled watch updates to subscribed chats."""

    app_context = _app_context(context)
    chat_id = int(context.job.data["chat_id"])
    user_id = int(context.job.data["user_id"])
    pair = str(context.job.data["pair"])

    try:
        await app_context.access_control_service.ensure_can_request(user_id=user_id)
        signal = await app_context.signal_service.get_signal(pair)
        await app_context.access_control_service.consume_request(user_id=user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_signal_message(
                signal,
                app_context.settings.display_timezone,
                app_context.settings.broker_style,
            ),
        )
        await _maybe_execute_autotrade(context, app_context, chat_id, user_id, signal)
    except (AccessDeniedError, QuotaExceededError) as exc:
        logger.info("Stopping watch for chat=%s pair=%s: %s", chat_id, pair, exc)
        context.job.schedule_removal()
        await app_context.subscription_service.remove(chat_id, pair)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"چاودێری بۆ {app_context.signal_service.display_pair(pair)} وەستاندرا "
                f"چونکە {_access_error_message(exc)}"
            ),
        )
    except Exception:
        logger.exception("Scheduled watch job failed for chat=%s pair=%s", chat_id, pair)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"نوێکردنەوەی ئاماژە بۆ {app_context.signal_service.display_pair(pair)} سەرکەوتوو نەبوو.",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled Telegram errors and return a generic message when possible."""

    logger.exception("Unhandled Telegram error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "بۆت تووشی هەڵەی ناوخۆیی بوو. تکایە دواتر هەوڵبدەرەوە.",
            reply_markup=build_main_menu_keyboard(),
        )


async def restore_watch_jobs(application: Application, app_context: AppContext) -> None:
    """Restore persisted watch jobs into the PTB job queue."""

    if application.job_queue is None:
        return
    records = await app_context.subscription_service.list_all()
    for record in records:
        _schedule_watch_job(
            application=application,
            chat_id=record.chat_id,
            user_id=record.user_id or record.chat_id,
            pair=record.pair,
            interval_seconds=record.interval_seconds,
        )


def _app_context(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    """Read the shared app context from the Telegram application."""

    return context.application.bot_data["app_context"]


def _required_pair_arg(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Return the first command argument when present."""

    if not context.args:
        return None
    return context.args[0]


def _job_name(chat_id: int, pair: str) -> str:
    """Build a stable job name for a watched pair."""

    return f"watch:{chat_id}:{pair}"


def _schedule_watch_job(
    application: Application,
    chat_id: int,
    user_id: int,
    pair: str,
    interval_seconds: int,
) -> None:
    """Create or replace a repeating watch job."""

    if application.job_queue is None:
        raise RuntimeError("Job queue is unavailable.")
    job_name = _job_name(chat_id, pair)
    for job in application.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    application.job_queue.run_repeating(
        watch_job_callback,
        interval=interval_seconds,
        first=interval_seconds,
        name=job_name,
        data={"chat_id": chat_id, "user_id": user_id, "pair": pair},
    )


async def _send_signal_from_callback(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    app_context: AppContext,
    pair: str,
) -> None:
    """Send a one-time signal after a pair was selected from the inline keyboard."""

    if query.from_user is None:
        return

    try:
        await app_context.access_control_service.ensure_can_request(
            user_id=query.from_user.id,
            username=query.from_user.username,
        )
        signal = await app_context.signal_service.get_signal(pair)
        await app_context.access_control_service.consume_request(
            user_id=query.from_user.id,
            username=query.from_user.username,
        )
    except (AccessDeniedError, QuotaExceededError) as exc:
        await query.edit_message_text(_access_error_message(exc))
        return
    except Exception:
        logger.exception("Signal callback failed")
        await query.edit_message_text("دروستکردنی ئاماژە سەرکەوتوو نەبوو. دواتر هەوڵبدەرەوە.")
        return

    await query.edit_message_text(
        format_signal_message(
            signal,
            app_context.settings.display_timezone,
            app_context.settings.broker_style,
        ),
    )
    if query.message is not None and query.message.chat is not None:
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="مێنیوی سەرەکی ئامادەیە.",
            reply_markup=build_main_menu_keyboard(),
        )


async def _start_watch_from_callback(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    app_context: AppContext,
    pair: str,
    interval_seconds: int,
) -> None:
    """Create or replace a watch after the user picks pair and interval."""

    if query.message is None or query.message.chat is None or query.from_user is None:
        return

    try:
        await app_context.access_control_service.ensure_can_request(
            user_id=query.from_user.id,
            username=query.from_user.username,
        )
        signal = await app_context.signal_service.get_signal(pair)
        await app_context.access_control_service.consume_request(
            user_id=query.from_user.id,
            username=query.from_user.username,
        )
    except (AccessDeniedError, QuotaExceededError) as exc:
        await query.edit_message_text(_access_error_message(exc))
        return
    except Exception:
        logger.exception("Watch callback failed")
        await query.edit_message_text("دەستپێکردنی چاودێری سەرکەوتوو نەبوو. دواتر هەوڵبدەرەوە.")
        return

    await app_context.subscription_service.upsert(
        chat_id=query.message.chat.id,
        user_id=query.from_user.id,
        pair=pair,
        interval_seconds=interval_seconds,
    )
    _schedule_watch_job(
        context.application,
        query.message.chat.id,
        query.from_user.id,
        pair,
        interval_seconds,
    )

    await query.edit_message_text(
        f"{app_context.signal_service.display_pair(pair)} هەموو {interval_seconds} چرکە چاودێری دەکرێت."
    )
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=format_signal_message(
            signal,
            app_context.settings.display_timezone,
            app_context.settings.broker_style,
        ),
        reply_markup=build_main_menu_keyboard(),
    )


async def _stop_watch_from_callback(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    app_context: AppContext,
    pair: str,
) -> None:
    """Stop a watch selected from the inline keyboard."""

    if query.message is None or query.message.chat is None:
        return

    job_name = _job_name(query.message.chat.id, pair)
    removed_job = False
    for job in context.job_queue.get_jobs_by_name(job_name):
        removed_job = True
        job.schedule_removal()

    removed_record = await app_context.subscription_service.remove(query.message.chat.id, pair)
    if removed_job or removed_record:
        await query.edit_message_text(
            f"نوێکردنەوەکان بۆ {app_context.signal_service.display_pair(pair)} وەستان."
        )
    else:
        await query.edit_message_text("هیچ چاودێرییەکی چالاک بۆ ئەو جووتە نەدۆزرایەوە.")

    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text="مێنیوی سەرەکی ئامادەیە.",
        reply_markup=build_main_menu_keyboard(),
    )


async def _reply(update: Update, text: str, reply_markup=None) -> None:
    """Reply to the active message when available."""

    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def _maybe_execute_autotrade(
    context: ContextTypes.DEFAULT_TYPE,
    app_context: AppContext,
    chat_id: int,
    user_id: int,
    signal,
) -> None:
    """Submit a stored-session trade when autotrade is enabled for the watching user."""

    profile = await app_context.execution_profile_service.get_profile_status(user_id)
    if profile is None or not profile.autotrade_enabled:
        return

    selected = signal.signals[profile.signal_horizon]
    if selected.signal == SignalLabel.HOLD:
        return

    side = OrderSide.BUY if selected.signal == SignalLabel.BUY else OrderSide.SELL
    try:
        response = await app_context.trading_service.place_market_order(
            MarketOrderRequest(
                pair=signal.pair,
                side=side,
                units=profile.trade_amount,
                request_source="telegram_watch_autotrade",
                requested_by=str(user_id),
            )
        )
    except Exception:
        logger.exception("Autotrade failed for user=%s pair=%s", user_id, signal.pair)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Autotrade failed for {signal.display_pair}.",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(
            [
                f"Autotrade executed from {profile.signal_horizon} signal {selected.signal.value} ({selected.confidence:.2f})",
                format_market_order_response(response),
            ]
        ),
    )


async def _place_market_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    side: OrderSide,
) -> None:
    """Execute an admin market order command."""

    app_context = _app_context(context)
    if not _is_admin(update, app_context):
        await _reply(update, "You are not allowed to use trading commands.")
        return
    if len(context.args) < 2:
        await _reply(update, f"Usage: /{side.value.lower()} EURUSD 100")
        return

    try:
        units = int(context.args[1])
    except ValueError:
        await _reply(update, "Units must be an integer.")
        return

    try:
        take_profit = float(context.args[2]) if len(context.args) >= 3 else None
        stop_loss = float(context.args[3]) if len(context.args) >= 4 else None
    except ValueError:
        await _reply(update, "TP/SL values must be numeric.")
        return

    try:
        response = await app_context.trading_service.place_market_order(
            MarketOrderRequest(
                pair=context.args[0],
                side=side,
                units=units,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
                request_source="telegram",
                requested_by=str(update.effective_user.id) if update.effective_user else None,
            )
        )
    except Exception as exc:
        logger.exception("Market order command failed")
        await _reply(update, str(exc))
        return

    await _reply(
        update,
        format_market_order_response(response),
        reply_markup=build_main_menu_keyboard(),
    )


def _is_admin(update: Update, app_context: AppContext) -> bool:
    """Return whether the Telegram user is allowed to trade."""

    if update.effective_user is None:
        return False
    return update.effective_user.id in app_context.settings.admin_telegram_user_ids


def _access_error_message(exc: Exception) -> str:
    """Translate access-control errors into concise Telegram text."""

    if isinstance(exc, QuotaExceededError):
        return (
            f"ئەمڕۆ سنووری داواکارییەکانت تەواوبووە "
            f"({exc.status.used_today}/{exc.status.daily_limit})."
        )
    if isinstance(exc, AccessDeniedError):
        return str(exc)
    return "Access request failed."
