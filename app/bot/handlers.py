"""Telegram command handlers and scheduled alert jobs."""

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
    format_account_summary,
    format_close_position_response,
    format_help_message,
    format_market_order_response,
    format_pairs,
    format_positions,
    format_signal_message,
    format_status,
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
from app.models.trading import ClosePositionRequest, MarketOrderRequest, OrderSide, PositionCloseSide

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
    application.add_handler(CommandHandler("account", account_command))
    application.add_handler(CommandHandler("positions", positions_command))
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
            "\n/account - account summary"
            "\n/positions - open positions"
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
    pair = _required_pair_arg(context)
    if not pair:
        await _reply(
            update,
            "جووتێک هەڵبژێرە بۆ ئاماژەیەکی یەکجار.",
            reply_markup=build_signal_pair_keyboard(app_context.signal_service.list_pairs()),
        )
        return

    try:
        signal = await app_context.signal_service.get_signal(pair)
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
        signal = await app_context.signal_service.get_signal(pair)
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
    _schedule_watch_job(context.application, update.effective_chat.id, pair, interval_seconds)

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
    pair = str(context.job.data["pair"])

    try:
        signal = await app_context.signal_service.get_signal(pair)
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_signal_message(
                signal,
                app_context.settings.display_timezone,
                app_context.settings.broker_style,
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
        data={"chat_id": chat_id, "pair": pair},
    )


async def _send_signal_from_callback(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    app_context: AppContext,
    pair: str,
) -> None:
    """Send a one-time signal after a pair was selected from the inline keyboard."""

    try:
        signal = await app_context.signal_service.get_signal(pair)
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
        signal = await app_context.signal_service.get_signal(pair)
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
    _schedule_watch_job(context.application, query.message.chat.id, pair, interval_seconds)

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
