"""Helper for building inline keyboards from graph nodes."""

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class NavCallbackData(CallbackData, prefix="nav"):
    """Callback data for navigation buttons. node_id must fit within 64-byte limit."""

    node_id: str


def back_kb(callback_data: str = "nav_back") -> InlineKeyboardMarkup:
    """Single back button keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callback_data,
                )
            ]
        ]
    )


def regen_kb(callback_data: str = "final_regen") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерировать",
                    callback_data=callback_data,
                )
            ]
        ]
    )


def menu_kb(callback_data: str = "nav_menu") -> InlineKeyboardMarkup:
    """Single 'back to main menu' button keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 В меню",
                    callback_data=callback_data,
                )
            ]
        ]
    )


def feedback_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍", callback_data="fb:like"),
                InlineKeyboardButton(text="👎", callback_data="fb:dislike"),
            ]
        ]
    )


def feedback_reasons_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Слишком длинно",
                    callback_data="fb:reason:too_long",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не тот тон",
                    callback_data="fb:reason:tone_bad",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мимо ситуации",
                    callback_data="fb:reason:miss_context",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другое",
                    callback_data="fb:reason:other",
                )
            ],
        ]
    )


def _append_back_row(
    keyboard: InlineKeyboardMarkup,
    callback_data: str = "nav_back",
) -> InlineKeyboardMarkup:
    """Append a back button row to an existing inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *keyboard.inline_keyboard,
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callback_data,
                )
            ],
        ]
    )


def _append_menu_row(
    keyboard: InlineKeyboardMarkup,
    callback_data: str = "nav_menu",
) -> InlineKeyboardMarkup:
    """Append a 'menu' button row to an existing inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *keyboard.inline_keyboard,
            [
                InlineKeyboardButton(
                    text="🏠 В меню",
                    callback_data=callback_data,
                )
            ],
        ]
    )


def with_back(
    keyboard: InlineKeyboardMarkup,
    callback_data: str = "nav_back",
) -> InlineKeyboardMarkup:
    """Public wrapper to add a back row to an existing keyboard."""
    return _append_back_row(keyboard, callback_data=callback_data)


def with_menu(
    keyboard: InlineKeyboardMarkup,
    callback_data: str = "nav_menu",
) -> InlineKeyboardMarkup:
    """Public wrapper to add a 'menu' row to an existing keyboard."""
    return _append_menu_row(keyboard, callback_data=callback_data)


def build_nav_keyboard(
    options: list[dict[str, Any]],
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard from a node's options.

    Args:
        options: List of dicts with 'label' and 'next_node' keys.

    Returns:
        InlineKeyboardMarkup with one button per option.
    """
    buttons = [
        [
            InlineKeyboardButton(
                text=opt["label"],
                callback_data=NavCallbackData(node_id=opt["next_node"]).pack(),
            )
        ]
        for opt in options
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if include_back:
        return _append_back_row(kb, callback_data="nav_back")
    return kb


def build_action_keyboard(
    label: str,
    action: str,
) -> InlineKeyboardMarkup:
    """
    Build a single-action keyboard (e.g. call emergency).

    Args:
        label: Button text.
        action: Action identifier.

    Returns:
        InlineKeyboardMarkup with one button.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"action:{action}",
                )
            ]
        ]
    )


def build_practice_mode_keyboard() -> InlineKeyboardMarkup:
    """Keyboard with Practice Mode button (shown below generated advice)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎭 Practice Mode",
                    callback_data="start_sim",
                )
            ]
        ]
    )


def build_stop_sim_keyboard() -> InlineKeyboardMarkup:
    """Keyboard with Stop Simulation button (shown during roleplay)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Stop Simulation",
                    callback_data="stop_sim",
                )
            ]
        ]
    )


def simulation_kb() -> InlineKeyboardMarkup:
    """Keyboard shown in Simulation mode (hint/draft/stop)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💡 Подсказка",
                    callback_data="sim:hint",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Stop Simulation",
                    callback_data="sim:stop",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 В меню",
                    callback_data="nav_menu",
                )
            ],
        ]
    )
