"""Telegram keyboard builders for the bot UI."""

from typing import Iterable, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.models.signal import SubscriptionRecord
from app.services.signal_service import SignalService


WATCH_INTERVAL_OPTIONS = [10, 15, 30, 60]

MAIN_MENU_SIGNAL = "ئاماژە بهێنە"
MAIN_MENU_WATCH = "جووت چاودێر بکە"
MAIN_MENU_STOP = "چاودێری بوەستێنە"
MAIN_MENU_STATUS = "دۆخی من"
MAIN_MENU_PAIRS = "جووتەکان"
MAIN_MENU_HELP = "یارمەتی"


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return the persistent main menu keyboard."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(MAIN_MENU_SIGNAL), KeyboardButton(MAIN_MENU_WATCH)],
            [KeyboardButton(MAIN_MENU_STOP), KeyboardButton(MAIN_MENU_STATUS)],
            [KeyboardButton(MAIN_MENU_PAIRS), KeyboardButton(MAIN_MENU_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def build_signal_pair_keyboard(pairs: Iterable[str]) -> InlineKeyboardMarkup:
    """Return the pair picker for one-off signals."""

    return _build_pair_keyboard(pairs, callback_prefix="signal")


def build_watch_pair_keyboard(pairs: Iterable[str]) -> InlineKeyboardMarkup:
    """Return the pair picker for watch subscriptions."""

    return _build_pair_keyboard(pairs, callback_prefix="watchpair")


def build_watch_interval_keyboard(pair: str) -> InlineKeyboardMarkup:
    """Return interval options for a pair watch."""

    rows = [
        [
            InlineKeyboardButton(
                text=f"{interval}s",
                callback_data=f"watchstart:{pair}:{interval}",
            )
            for interval in WATCH_INTERVAL_OPTIONS[:2]
        ],
        [
            InlineKeyboardButton(
                text=f"{interval}s",
                callback_data=f"watchstart:{pair}:{interval}",
            )
            for interval in WATCH_INTERVAL_OPTIONS[2:]
        ],
    ]
    rows.append([InlineKeyboardButton(text="هەڵوەشاندنەوە", callback_data="menu:cancel")])
    return InlineKeyboardMarkup(rows)


def build_stop_watch_keyboard(records: List[SubscriptionRecord]) -> InlineKeyboardMarkup:
    """Return active watch controls for stopping subscriptions."""

    rows = [
        [
            InlineKeyboardButton(
                text=f"وەستاندنی {SignalService.display_pair(record.pair)}",
                callback_data=f"stop:{record.pair}",
            )
        ]
        for record in records
    ]
    rows.append([InlineKeyboardButton(text="هەڵوەشاندنەوە", callback_data="menu:cancel")])
    return InlineKeyboardMarkup(rows)


def _build_pair_keyboard(pairs: Iterable[str], callback_prefix: str) -> InlineKeyboardMarkup:
    """Build a compact pair selection keyboard."""

    normalized_pairs = list(pairs)
    rows = []
    for index in range(0, len(normalized_pairs), 2):
        chunk = normalized_pairs[index : index + 2]
        rows.append(
            [
                InlineKeyboardButton(
                    text=SignalService.display_pair(pair),
                    callback_data=f"{callback_prefix}:{pair}",
                )
                for pair in chunk
            ]
        )
    rows.append([InlineKeyboardButton(text="هەڵوەشاندنەوە", callback_data="menu:cancel")])
    return InlineKeyboardMarkup(rows)
