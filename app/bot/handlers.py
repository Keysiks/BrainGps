"""Main bot handlers: navigation, wizard, static results."""

import asyncio
import html
import uuid
from typing import Any

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards import (
    NavCallbackData,
    back_kb,
    build_action_keyboard,
    build_nav_keyboard,
    build_practice_mode_keyboard,
    build_stop_sim_keyboard,
    feedback_kb,
    feedback_reasons_kb,
    menu_kb,
    regen_kb,
    simulation_kb,
    with_back,
    with_menu,
)
from app.bot.states import Feedback, Form, Simulation
from app.core.feedback_db import save_feedback
from app.core.graph import get_root_node_id, load_graph
from app.core.llm import LLMService

router = Router(name="brain_gps")

# Module-level graph and LLM (initialized in main.py)
GLOBAL_GRAPH: dict[str, Any] = {}
LLM_SERVICE: LLMService | None = None

# Last simulation context per user (for Practice Mode button)
LAST_SIMULATION_CONTEXT: dict[int, dict[str, Any]] = {}


async def _safe_callback_answer(callback: CallbackQuery, *args: Any, **kwargs: Any) -> None:
    """Answer callback query but ignore cases when query is already expired."""
    try:
        await callback.answer(*args, **kwargs)
    except TelegramBadRequest:
        return


async def _push_nav(state: FSMContext, next_node_id: str) -> None:
    """Push current node to nav_stack and set current_view_node_id=next_node_id."""
    data = await state.get_data()
    current = data.get("current_view_node_id")
    stack = data.get("nav_stack")
    if not isinstance(stack, list):
        stack = []
    if isinstance(current, str) and current:
        stack.append(current)
    await state.update_data(nav_stack=stack, current_view_node_id=next_node_id)


def _feedback_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Спасибо за фидбек",
                    callback_data="fb:done",
                )
            ]
        ]
    )


def _remove_feedback_rows(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        has_fb = False
        for btn in row:
            cd = getattr(btn, "callback_data", None)
            if isinstance(cd, str) and cd.startswith("fb:"):
                has_fb = True
                break
        if not has_fb:
            rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _mark_feedback_done_on_message(
    *,
    message: Message,
    state: FSMContext,
    base_keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    data = await state.get_data()
    last_mid = data.get("last_answer_message_id")
    if isinstance(last_mid, int) and message.message_id != last_mid:
        return

    if base_keyboard is None:
        base_keyboard = _remove_feedback_rows(message.reply_markup)
    if base_keyboard is None:
        base_keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    new_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            *base_keyboard.inline_keyboard,
            *_feedback_done_kb().inline_keyboard,
        ]
    )

    try:
        await message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        return


async def _send_main_menu(message: Message, state: FSMContext) -> None:
    root_id = get_root_node_id(GLOBAL_GRAPH)
    root_node = GLOBAL_GRAPH.get(root_id, {})
    await state.update_data(
        nav_stack=[],
        current_view_node_id=root_id,
        session_id=str(uuid.uuid4()),
        last_strategy_id=None,
        last_branch=None,
        pending_feedback=None,
        pending_feedback_message=None,
        feedback_sent_for_message_id=None,
    )
    await message.answer(
        text=root_node.get("text", "Главное меню"),
        reply_markup=build_nav_keyboard(root_node.get("options", [])),
    )


def _branch_from_node_id(node_id: str) -> str | None:
    if node_id.startswith("work_") or node_id.startswith("work"):
        return "work"
    if (
        node_id.startswith("family_")
        or node_id.startswith("family")
        or node_id.startswith("strat_fam")
        or node_id.startswith("strat_dating")
        or node_id.startswith("strat_ex")
    ):
        return "family"
    if node_id.startswith("sos_") or node_id.startswith("sos") or node_id.startswith("strat_sos"):
        return "sos"
    return None


def _sim_defaults_for_branch(branch: str | None) -> dict[str, str]:
    if branch == "family":
        return {
            "role_name": "Партнер",
            "opponent_style": "partner_emotional",
            "swearing_allowed": "no",
        }
    if branch == "sos":
        return {
            "role_name": "Оппонент",
            "opponent_style": "aggressive",
            "swearing_allowed": "no",
        }
    return {
        "role_name": "Оппонент",
        "opponent_style": "calm_incident_manager",
        "swearing_allowed": "no",
    }


async def _can_go_back(state: FSMContext) -> bool:
    data = await state.get_data()
    stack = data.get("nav_stack")
    return isinstance(stack, list) and len(stack) > 0


def init_handlers(graph: dict[str, Any], llm_service: LLMService) -> None:
    """Inject graph and LLM service. Call from main.py after loading."""
    global GLOBAL_GRAPH, LLM_SERVICE
    GLOBAL_GRAPH = graph
    LLM_SERVICE = llm_service


def _format_static_result(node: dict[str, Any]) -> str:
    """Format static_result node for display."""
    header = node.get("ui_header", "")
    content = node.get("static_content", [])
    lines = [f"<b>{header}</b>\n"]
    for item in content:
        title = item.get("title", "")
        text = item.get("text", "")
        lines.append(f"<b>{title}</b>\n{text}")
    return "\n".join(lines)


async def _show_node(
    message_or_callback: Message | CallbackQuery,
    node_id: str,
    state: FSMContext | None = None,
) -> None:
    """Show a question node (text + keyboard)."""
    node = GLOBAL_GRAPH.get(node_id)
    if not node or node.get("type") != "question":
        return

    text = node.get("text", "")
    options = node.get("options", [])
    include_back = False
    if state is not None:
        include_back = await _can_go_back(state)
    keyboard = build_nav_keyboard(options, include_back=include_back)
    keyboard = with_menu(keyboard)

    if isinstance(message_or_callback, CallbackQuery):
        q = message_or_callback
        await q.message.edit_text(text=text, reply_markup=keyboard)
        await q.answer()
    else:
        await message_or_callback.answer(text=text, reply_markup=keyboard)


async def _send_static_result(
    message_or_callback: Message | CallbackQuery,
    node: dict[str, Any],
    state: FSMContext | None = None,
) -> None:
    """Send static_result content and optional action button."""
    formatted = _format_static_result(node)
    action_btn = node.get("action_button")

    keyboard = None
    if action_btn:
        keyboard = build_action_keyboard(
            label=action_btn.get("label", "Действие"),
            action=action_btn.get("action", ""),
        )

    if keyboard is None:
        if state is not None and await _can_go_back(state):
            keyboard = with_back(menu_kb())
        else:
            keyboard = menu_kb()
    else:
        if state is not None and await _can_go_back(state):
            keyboard = with_back(keyboard)

        keyboard = with_menu(keyboard)

    if isinstance(message_or_callback, CallbackQuery):
        q = message_or_callback
        await q.message.edit_text(
            text=formatted,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await q.answer()
    else:
        await message_or_callback.answer(
            text=formatted,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


async def _start_input_wizard(
    message_or_callback: Message | CallbackQuery,
    node_id: str,
    state: FSMContext,
) -> None:
    """Start input gathering for a final (strategy) node."""
    node = GLOBAL_GRAPH.get(node_id)
    if not node or node.get("type") != "final":
        return

    input_fields = node.get("input_fields") or []

    if not input_fields:
        # No inputs: call LLM immediately with empty context
        await _generate_and_send(message_or_callback, node_id, {})
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer()
        return

    await state.update_data(
        current_node_id=node_id,
        inputs_buffer={},
        current_field_index=0,
    )
    await state.set_state(Form.collecting_input)

    field = input_fields[0]
    label = field.get("label", "Введите значение")
    placeholder = field.get("placeholder", "")

    prompt = label
    if placeholder:
        prompt = f"{label}\n\nПример: {placeholder}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *back_kb(callback_data="wiz:back").inline_keyboard,
            *menu_kb().inline_keyboard,
        ]
    )

    if isinstance(message_or_callback, CallbackQuery):
        q = message_or_callback
        await q.message.edit_text(text=prompt, reply_markup=keyboard)
        await q.answer()
    else:
        await message_or_callback.answer(text=prompt, reply_markup=keyboard)


async def _generate_and_send(
    target: Message | CallbackQuery,
    node_id: str,
    inputs: dict[str, str],
    state: FSMContext | None = None,
) -> None:
    """Call LLM and send the result, with Practice Mode button."""
    user_id = target.from_user.id if target.from_user else 0
    LAST_SIMULATION_CONTEXT[user_id] = {"node_id": node_id, "inputs": inputs}

    if not LLM_SERVICE:
        result = "Ошибка: LLM сервис не настроен."
    else:
        node = GLOBAL_GRAPH.get(node_id)
        template_name = node.get("prompt_template", "work_template.j2")
        llm_config = node.get("llm_config", {})
        ui_description = node.get("ui_description", "")

        context = {
            "config": llm_config,
            "inputs": inputs,
            "ui_description": ui_description,
        }
        result = await asyncio.to_thread(
            LLM_SERVICE.generate_advice,
            template_name,
            context,
        )

    node = GLOBAL_GRAPH.get(node_id, {})
    strategy_name = (node.get("llm_config") or {}).get("strategy_name")
    safe_result = html.escape(result)
    if node_id == "strat_ex_panic_button" or strategy_name == "Reality Slap (Пощечина реальностью)":
        safe_result = f"<b>НЕ ПИШИ ЕЙ СЕЙЧАС.</b>\n\n{safe_result}"

    if state is not None:
        await state.update_data(
            last_strategy_id=node_id,
            last_branch=_branch_from_node_id(node_id),
            last_generated_node_id=node_id,
            last_generated_inputs=inputs,
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *regen_kb().inline_keyboard,
            *build_practice_mode_keyboard().inline_keyboard,
        ]
    )
    if state is not None and await _can_go_back(state):
        keyboard = with_back(keyboard)

    keyboard = with_menu(keyboard)

    if state is not None:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                *keyboard.inline_keyboard,
                *feedback_kb().inline_keyboard,
            ]
        )
    sent: Message | None = None
    if isinstance(target, CallbackQuery):
        sent = await target.message.edit_text(
            text=safe_result,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        sent = await target.answer(
            text=safe_result,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    if state is not None and sent is not None:
        await state.update_data(
            last_answer_chat_id=sent.chat.id,
            last_answer_message_id=sent.message_id,
            feedback_sent_for_message_id=None,
            pending_feedback_message=None,
        )


# --- Handlers ---


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start: show root node."""
    await state.clear()
    if message.from_user:
        LAST_SIMULATION_CONTEXT.pop(message.from_user.id, None)

    hint = (
        "Как пользоваться:\n"
        "- Выбирай варианты кнопками, чтобы быстро классифицировать ситуацию.\n"
        "- Если ошибся — жми ⬅️ Назад.\n"
        "- В конце я сгенерирую готовый скрипт ответа.\n"
        "- Можно включить 🎭 Practice Mode, чтобы потренироваться в диалоге."
    )
    await message.answer(hint)

    root_id = get_root_node_id(GLOBAL_GRAPH)
    await state.update_data(
        nav_stack=[],
        current_view_node_id=root_id,
        session_id=str(uuid.uuid4()),
        last_strategy_id=None,
        last_branch=None,
        pending_feedback=None,
    )
    await _show_node(message, root_id, state)


@router.callback_query(NavCallbackData.filter())
async def on_nav_callback(
    callback: CallbackQuery,
    callback_data: NavCallbackData,
    state: FSMContext,
) -> None:
    """Handle navigation button click."""
    node_id = callback_data.node_id
    node = GLOBAL_GRAPH.get(node_id)

    if not node:
        await callback.answer("Неизвестный узел.", show_alert=True)
        return

    node_type = node.get("type")

    if node_type == "question":
        await _push_nav(state, node_id)
        await _show_node(callback, node_id, state)
    elif node_type == "static_result":
        await _push_nav(state, node_id)
        await _send_static_result(callback, node, state)
    elif node_type == "final":
        await _push_nav(state, node_id)
        await _start_input_wizard(callback, node_id, state)
    else:
        await callback.answer("Неизвестный тип узла.", show_alert=True)


@router.callback_query(F.data == "nav_back")
async def nav_back(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state == Simulation.active.state:
        await callback.answer()
        return

    data = await state.get_data()
    stack = data.get("nav_stack")
    if not isinstance(stack, list) or not stack:
        await callback.answer()
        return

    prev_node_id = stack.pop()
    update: dict[str, Any] = {"nav_stack": stack, "current_view_node_id": prev_node_id}
    if prev_node_id == get_root_node_id(GLOBAL_GRAPH):
        update.update(
            session_id=str(uuid.uuid4()),
            last_strategy_id=None,
            last_branch=None,
            pending_feedback=None,
        )
    await state.update_data(**update)
    await _show_node(callback, prev_node_id, state)


@router.callback_query(F.data == "nav_menu")
async def nav_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Return user to root menu (work/relationships/sos) from anywhere."""
    await _safe_callback_answer(callback)
    data_before_clear = await state.get_data()
    sim_meta: dict[str, Any] | None = None
    if isinstance(data_before_clear, dict) and data_before_clear.get("sim_node_id"):
        sim_history = data_before_clear.get("sim_history")
        sim_meta = {
            "where": "simulation",
            "sim_node_id": data_before_clear.get("sim_node_id"),
            "sim_strategy_name": data_before_clear.get("sim_strategy_name"),
            "sim_turns": len(sim_history) if isinstance(sim_history, list) else None,
        }

    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    LAST_SIMULATION_CONTEXT.pop(user_id, None)

    root_id = get_root_node_id(GLOBAL_GRAPH)
    root_node = GLOBAL_GRAPH.get(root_id, {})
    await state.update_data(
        nav_stack=[],
        current_view_node_id=root_id,
        session_id=str(uuid.uuid4()),
        last_strategy_id=None,
        last_branch=None,
        pending_feedback=None,
        last_simulation_meta=sim_meta,
    )

    if callback.message:
        await callback.message.answer(
            text=root_node.get("text", "Главное меню"),
            reply_markup=build_nav_keyboard(root_node.get("options", [])),
        )
    await _safe_callback_answer(callback)


@router.callback_query(F.data.startswith("action:"))
async def on_action_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _safe_callback_answer(callback)
    action = (callback.data or "").split(":", 1)[1] if callback.data else ""
    if action == "call_emergency":
        text = (
            "Если есть непосредственная угроза жизни/здоровью — прямо сейчас позвони 112. "
            "Если можешь — укажи адрес и что происходит."
        )
        await callback.message.answer(text=text, reply_markup=menu_kb())
        await _safe_callback_answer(callback)
        return

    await _safe_callback_answer(callback, "Неизвестное действие", show_alert=False)


@router.callback_query(F.data == "final_regen")
async def final_regen(callback: CallbackQuery, state: FSMContext) -> None:
    await _safe_callback_answer(callback)
    data = await state.get_data()
    node_id = data.get("last_generated_node_id")
    inputs = data.get("last_generated_inputs")
    if not isinstance(node_id, str) or not node_id:
        await _safe_callback_answer(callback, "Нечего перегенерировать", show_alert=True)
        return
    if not isinstance(inputs, dict):
        inputs = {}

    await state.update_data(
        feedback_sent_for_message_id=None,
        pending_feedback_message=None,
    )
    await _generate_and_send(callback, node_id, inputs, state)
    await _safe_callback_answer(callback)


@router.callback_query(F.data == "fb:like")
async def feedback_like(callback: CallbackQuery, state: FSMContext) -> None:
    await _safe_callback_answer(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    data = await state.get_data()
    if (
        isinstance(data.get("feedback_sent_for_message_id"), int)
        and data.get("feedback_sent_for_message_id") == data.get("last_answer_message_id")
    ):
        await _safe_callback_answer(callback, "Фидбек уже записан", show_alert=False)
        return
    session_id = data.get("session_id") or str(uuid.uuid4())

    await save_feedback(
        user_id=user_id,
        session_id=session_id,
        rating=1,
        reason_code=None,
        comment=None,
        branch=data.get("last_branch"),
        node_id=data.get("current_view_node_id"),
        strategy_id=data.get("last_strategy_id"),
        model=None,
        latency_ms=None,
        meta={"where": "final_answer"},
    )
    await state.update_data(feedback_sent_for_message_id=data.get("last_answer_message_id"))
    await _mark_feedback_done_on_message(message=callback.message, state=state)
    await _safe_callback_answer(callback, "Спасибо!", show_alert=False)


@router.callback_query(F.data == "fb:dislike")
async def feedback_dislike(callback: CallbackQuery, state: FSMContext) -> None:
    await _safe_callback_answer(callback)
    data = await state.get_data()
    if (
        isinstance(data.get("feedback_sent_for_message_id"), int)
        and data.get("feedback_sent_for_message_id") == data.get("last_answer_message_id")
    ):
        await _safe_callback_answer(callback, "Фидбек уже записан", show_alert=False)
        return
    await state.update_data(
        pending_feedback={"rating": 0},
        pending_feedback_message={
            "chat_id": callback.message.chat.id,
            "message_id": callback.message.message_id,
        },
    )
    await callback.message.answer("Почему не зашло?", reply_markup=feedback_reasons_kb())
    await _safe_callback_answer(callback)


@router.callback_query(F.data.startswith("fb:reason:"))
async def feedback_reason(callback: CallbackQuery, state: FSMContext) -> None:
    await _safe_callback_answer(callback)
    reason_code = callback.data.split(":", 2)[2]
    data = await state.get_data()
    if (
        isinstance(data.get("feedback_sent_for_message_id"), int)
        and data.get("feedback_sent_for_message_id") == data.get("last_answer_message_id")
    ):
        await _safe_callback_answer(callback, "Фидбек уже записан", show_alert=False)
        return
    pending = data.get("pending_feedback") if isinstance(data.get("pending_feedback"), dict) else {}
    pending = {**pending, "reason_code": reason_code}
    await state.update_data(pending_feedback=pending)

    if reason_code == "other":
        await state.set_state(Feedback.comment)
        await callback.message.answer("Ок. Напиши короткий комментарий (1-2 предложения).")
        await _safe_callback_answer(callback)
        return

    user_id = callback.from_user.id if callback.from_user else 0
    session_id = data.get("session_id") or str(uuid.uuid4())
    await save_feedback(
        user_id=user_id,
        session_id=session_id,
        rating=0,
        reason_code=reason_code,
        comment=None,
        branch=data.get("last_branch"),
        node_id=data.get("current_view_node_id"),
        strategy_id=data.get("last_strategy_id"),
        model=None,
        latency_ms=None,
        meta={"where": "final_answer"},
    )
    await state.update_data(pending_feedback=None)
    await state.update_data(feedback_sent_for_message_id=data.get("last_answer_message_id"))
    await _mark_feedback_done_on_message(message=callback.message, state=state)
    await _send_main_menu(callback.message, state)
    await callback.answer("Принято", show_alert=False)


@router.message(Feedback.comment)
async def feedback_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши текстом, пожалуйста.")
        return
    comment = message.text.strip()
    data = await state.get_data()
    pending = data.get("pending_feedback") if isinstance(data.get("pending_feedback"), dict) else {}
    reason_code = pending.get("reason_code")

    user_id = message.from_user.id if message.from_user else 0
    session_id = data.get("session_id") or str(uuid.uuid4())
    await save_feedback(
        user_id=user_id,
        session_id=session_id,
        rating=0,
        reason_code=reason_code,
        comment=comment,
        branch=data.get("last_branch"),
        node_id=data.get("current_view_node_id"),
        strategy_id=data.get("last_strategy_id"),
        model=None,
        latency_ms=None,
        meta={"where": "final_answer"},
    )
    await state.update_data(
        pending_feedback=None,
        feedback_sent_for_message_id=data.get("last_answer_message_id"),
    )
    await state.set_state(None)

    base_keyboard = build_practice_mode_keyboard()
    if await _can_go_back(state):
        base_keyboard = with_back(base_keyboard)
    base_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *base_keyboard.inline_keyboard,
            *_feedback_done_kb().inline_keyboard,
        ]
    )

    pending_msg = data.get("pending_feedback_message")
    if isinstance(pending_msg, dict):
        chat_id = pending_msg.get("chat_id")
        message_id = pending_msg.get("message_id")
        if isinstance(chat_id, int) and isinstance(message_id, int):
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=base_keyboard,
                )
            except Exception:
                pass

    await state.update_data(pending_feedback_message=None)
    await message.answer("Спасибо, записал.")
    await _send_main_menu(message, state)


@router.callback_query(F.data == "fb:done")
async def feedback_done(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "start_sim")
async def start_simulation(callback: CallbackQuery, state: FSMContext) -> None:
    """Start Practice Mode: AI plays the opponent."""
    user_id = callback.from_user.id if callback.from_user else 0
    ctx = LAST_SIMULATION_CONTEXT.get(user_id)
    if not ctx:
        await callback.answer("Контекст не найден. Пройдите стратегию заново.", show_alert=True)
        return

    node = GLOBAL_GRAPH.get(ctx["node_id"], {})
    llm_config = node.get("llm_config", {}) if isinstance(node, dict) else {}
    strategy_name = llm_config.get("strategy_name") if isinstance(llm_config, dict) else None
    strategy_rules = llm_config.get("rules") if isinstance(llm_config, dict) else None
    branch = _branch_from_node_id(ctx["node_id"])
    defaults = _sim_defaults_for_branch(branch)
    role_name = llm_config.get("role_name") if isinstance(llm_config, dict) else None
    opponent_style = llm_config.get("opponent_style") if isinstance(llm_config, dict) else None
    swearing_allowed = llm_config.get("swearing_allowed") if isinstance(llm_config, dict) else None

    if not isinstance(role_name, str) or not role_name:
        role_name = defaults["role_name"]
    if not isinstance(opponent_style, str) or not opponent_style:
        opponent_style = defaults["opponent_style"]
    if not isinstance(swearing_allowed, str) or not swearing_allowed:
        swearing_allowed = defaults["swearing_allowed"]
    if not isinstance(strategy_rules, list):
        strategy_rules = []

    sim_context = "\n".join(f"{k}: {v}" for k, v in ctx["inputs"].items()) or "—"
    if ctx["node_id"] in {"strat_fam_scandal_stop", "strat_fam_scandal_contain"}:
        sim_context = (
            "РОЛИ: Ты — супруг(а), который(ая) только что сорвался(ась): кричал(а)/оскорблял(а). "
            "Пользователь — тот, кого обидели. "
            "Не говори от лица пользователя и не объявляй, что 'берешь паузу' вместо него.\n"
            + sim_context
        )

    await state.update_data(
        sim_node_id=ctx["node_id"],
        sim_inputs=ctx["inputs"],
        sim_history=[],
        sim_context=sim_context,
        sim_strategy_name=strategy_name,
        sim_strategy_rules=strategy_rules,
        sim_role_name=role_name,
        sim_opponent_style=opponent_style,
        sim_swearing_allowed=swearing_allowed,
        last_user_message=None,
        last_opponent_message=None,
    )
    await state.set_state(Simulation.active)

    rules_for_sheet = strategy_rules[:6] if strategy_rules else []
    if rules_for_sheet:
        bullets = "\n".join(f"- {r}" for r in rules_for_sheet)
    else:
        if branch == "family":
            bullets = "\n".join(
                [
                    "- 1 фраза: что я почувствовал(а) / что мне неприятно",
                    "- 1 фраза: граница (что так нельзя)",
                    "- 1 фраза: что я хочу вместо этого",
                    "- без оправданий и лекций",
                ]
            )
        else:
            bullets = "\n".join(
                [
                    "- Коротко: факт → что делаю",
                    "- ETA (когда будет ок)",
                    "- Следующий апдейт (когда и что)",
                    "- Что нужно от оппонента (1 вопрос/действие)",
                ]
            )
    await callback.message.answer(text=f"🎭 Тренажер: правила\n\n{bullets}")

    welcome = (
        "Режим активирован. Я теперь играю роль вашего оппонента. "
        "Отправьте первое сообщение."
    )
    await callback.message.edit_text(
        text=welcome,
        reply_markup=simulation_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "stop_sim")
async def stop_simulation(callback: CallbackQuery, state: FSMContext) -> None:
    """Exit Practice Mode and show main menu."""
    data_before_clear = await state.get_data()
    sim_meta: dict[str, Any] | None = None
    if isinstance(data_before_clear, dict) and data_before_clear.get("sim_node_id"):
        sim_history = data_before_clear.get("sim_history")
        sim_meta = {
            "where": "simulation",
            "sim_node_id": data_before_clear.get("sim_node_id"),
            "sim_strategy_name": data_before_clear.get("sim_strategy_name"),
            "sim_turns": len(sim_history) if isinstance(sim_history, list) else None,
        }

    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    LAST_SIMULATION_CONTEXT.pop(user_id, None)

    await callback.message.edit_text(text="Симуляция остановлена.")
    await callback.answer()

    root_id = get_root_node_id(GLOBAL_GRAPH)
    root_node = GLOBAL_GRAPH[root_id]
    await state.update_data(
        nav_stack=[],
        current_view_node_id=root_id,
        session_id=str(uuid.uuid4()),
        last_strategy_id=None,
        last_branch=None,
        pending_feedback=None,
        last_simulation_meta=sim_meta,
    )
    await callback.message.answer(
        text=root_node.get("text", "Главное меню"),
        reply_markup=build_nav_keyboard(root_node.get("options", [])),
    )


@router.callback_query(Simulation.active, F.data == "sim:stop")
async def stop_simulation_v2(callback: CallbackQuery, state: FSMContext) -> None:
    """Exit Practice Mode (new callback) and show main menu."""
    await stop_simulation(callback, state)


@router.message(Simulation.active)
async def process_sim_message(message: Message, state: FSMContext) -> None:
    """Handle user message in Practice Mode; generate opponent reply."""
    if not message.text:
        await message.answer("Пожалуйста, введите текст.")
        return

    user_text = message.text.strip()
    data = await state.get_data()
    sim_inputs: dict = data.get("sim_inputs", {})
    sim_history: list = data.get("sim_history", [])

    llm_user_message = user_text
    sim_node_id = data.get("sim_node_id")
    if sim_node_id in {"strat_fam_scandal_stop", "strat_fam_scandal_contain"}:
        llm_user_message = (
            "(Это сообщение пользователя, адресовано ТЕБЕ — оппоненту. Пользователь описывает свои действия/границы.)\n"
            f"{user_text}"
        )

    await state.update_data(last_user_message=user_text)

    sim_history.append({"role": "user", "text": user_text})

    if not LLM_SERVICE:
        reply = "Ошибка: LLM сервис не настроен."
    else:
        sim_context = data.get("sim_context")
        if not isinstance(sim_context, str) or not sim_context:
            sim_context = "\n".join(f"{k}: {v}" for k, v in sim_inputs.items()) or "—"
            await state.update_data(sim_context=sim_context)
        reply = await asyncio.to_thread(
            LLM_SERVICE.generate_sim_response,
            sim_context,
            sim_history[:-1],
            llm_user_message,
            data.get("sim_role_name"),
            data.get("sim_opponent_style"),
            data.get("sim_swearing_allowed"),
        )

    sim_history.append({"role": "opponent", "text": reply})
    await state.update_data(
        sim_history=sim_history,
        last_opponent_message=reply,
    )

    await message.answer(
        text=f"<b>Оппонент:</b> {reply}",
        reply_markup=simulation_kb(),
        parse_mode="HTML",
    )


@router.callback_query(Simulation.active, F.data == "sim:hint")
async def simulation_hint(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    last_opponent_message = data.get("last_opponent_message")
    if not isinstance(last_opponent_message, str) or not last_opponent_message.strip():
        await callback.answer("Сначала отправь сообщение, чтобы я ответил оппонентом.", show_alert=True)
        return

    if not LLM_SERVICE:
        await callback.message.answer("Ошибка: LLM сервис не настроен.", reply_markup=simulation_kb())
        await callback.answer()
        return

    sim_context = data.get("sim_context")
    if not isinstance(sim_context, str) or not sim_context:
        sim_inputs: dict = data.get("sim_inputs", {})
        sim_context = "\n".join(f"{k}: {v}" for k, v in sim_inputs.items()) or "—"
        await state.update_data(sim_context=sim_context)

    history = data.get("sim_history", [])
    if not isinstance(history, list):
        history = []
    history = history[-8:]

    hint = await LLM_SERVICE.generate_coach_hint(
        context=sim_context,
        strategy_name=data.get("sim_strategy_name"),
        strategy_rules=data.get("sim_strategy_rules"),
        history=history,
        last_user_message=data.get("last_user_message"),
        last_opponent_message=last_opponent_message,
    )

    await callback.message.answer(text=hint, reply_markup=simulation_kb())
    await callback.answer()


@router.message(Form.collecting_input)
async def on_input_during_wizard(message: Message, state: FSMContext) -> None:
    """Handle any message during wizard. Redirect non-text to retry."""
    if not message.text:
        await message.answer("Пожалуйста, введите текст ответа.")
        return
    await _process_input_text(message, state)


async def _process_input_text(message: Message, state: FSMContext) -> None:
    """Process user text and advance wizard or generate advice."""
    data = await state.get_data()
    node_id = data.get("current_node_id")
    inputs_buffer: dict = data.get("inputs_buffer", {})
    current_index: int = data.get("current_field_index", 0)

    node = GLOBAL_GRAPH.get(node_id)
    if not node or node.get("type") != "final":
        await state.clear()
        return

    input_fields = node.get("input_fields") or []
    if current_index >= len(input_fields):
        await state.set_state(None)
        return

    field = input_fields[current_index]
    key = field.get("key", f"field_{current_index}")
    inputs_buffer[key] = message.text.strip()
    current_index += 1

    if current_index >= len(input_fields):
        await state.set_state(None)
        await _generate_and_send(message, node_id, inputs_buffer, state)
        return

    await state.update_data(
        inputs_buffer=inputs_buffer,
        current_field_index=current_index,
    )

    next_field = input_fields[current_index]
    label = next_field.get("label", "Введите значение")
    placeholder = next_field.get("placeholder", "")
    prompt = label
    if placeholder:
        prompt = f"{label}\n\nПример: {placeholder}"

    await message.answer(text=prompt, reply_markup=back_kb(callback_data="wiz:back"))


@router.callback_query(Form.collecting_input, F.data == "wiz:back")
async def wizard_back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    node_id = data.get("current_node_id")
    current_index: int = data.get("current_field_index", 0)
    inputs_buffer: dict = data.get("inputs_buffer", {})

    if not isinstance(node_id, str) or not node_id:
        await callback.answer()
        return

    if current_index <= 0:
        await state.set_state(None)
        data2 = await state.get_data()
        stack = data2.get("nav_stack")
        if isinstance(stack, list) and stack:
            prev_node_id = stack.pop()
            update2: dict[str, Any] = {"nav_stack": stack, "current_view_node_id": prev_node_id}
            if prev_node_id == get_root_node_id(GLOBAL_GRAPH):
                update2.update(
                    session_id=str(uuid.uuid4()),
                    last_strategy_id=None,
                    last_branch=None,
                    pending_feedback=None,
                )
            await state.update_data(**update2)
            await _show_node(callback, prev_node_id, state)
        else:
            root_id = get_root_node_id(GLOBAL_GRAPH)
            await state.update_data(nav_stack=[], current_view_node_id=root_id)
            await _show_node(callback, root_id, state)
        await callback.answer()
        return

    current_index -= 1
    if isinstance(inputs_buffer, dict):
        field_key_to_remove = None
        node = GLOBAL_GRAPH.get(node_id)
        input_fields = node.get("input_fields") if isinstance(node, dict) else None
        if isinstance(input_fields, list) and current_index < len(input_fields):
            field = input_fields[current_index]
            field_key_to_remove = field.get("key") if isinstance(field, dict) else None
        if field_key_to_remove and field_key_to_remove in inputs_buffer:
            inputs_buffer.pop(field_key_to_remove, None)

    await state.update_data(inputs_buffer=inputs_buffer, current_field_index=current_index)

    node = GLOBAL_GRAPH.get(node_id)
    input_fields = node.get("input_fields") if isinstance(node, dict) else None
    if not isinstance(input_fields, list) or current_index >= len(input_fields):
        await callback.answer()
        return
    field = input_fields[current_index]
    label = field.get("label", "Введите значение") if isinstance(field, dict) else "Введите значение"
    placeholder = field.get("placeholder", "") if isinstance(field, dict) else ""
    prompt = label
    if placeholder:
        prompt = f"{label}\n\nПример: {placeholder}"

    await callback.message.edit_text(text=prompt, reply_markup=back_kb(callback_data="wiz:back"))
    await callback.answer()
