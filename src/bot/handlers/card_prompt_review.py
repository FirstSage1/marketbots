"""Предварительный просмотр промпта и добровольные поправки до генерации."""

from contextlib import suppress
from secrets import token_hex

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.bot.handlers.card_runtime import isolation
from src.bot.states.card import CardStates
from src.services.card_prompts import amend_card_prompt
from src.utils.i18n import Localization

router = Router(name="card_prompt_review")


async def show_prompt_review(
    message: Message, state: FSMContext, l10n: Localization, prompt: str
) -> None:
    """Сделать действительной только последнюю версию показанного промпта."""
    data = await state.get_data()
    token = token_hex(6)
    session_id = str(data["session_id"])
    generate_key = (
        "card_prompt_confirm" if data.get("prompt_changes") else "card_prompt_generate"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.get("card_prompt_edit"),
                    callback_data=f"card_prompt:{session_id}:{token}:edit",
                )
            ],
            [
                InlineKeyboardButton(
                    text=l10n.get(generate_key),
                    callback_data=f"card_generate:{session_id}:{token}",
                )
            ],
        ]
    )
    preview = await message.answer(
        l10n.get("card_prompt_heading")
        + "\n\n"
        + prompt
        + "\n\n"
        + l10n.get("card_prompt_review"),
        reply_markup=keyboard,
        parse_mode=None,
    )
    await state.update_data(
        final_prompt=prompt, prompt_revision=token, prompt_menu_id=preview.message_id
    )
    await state.set_state(CardStates.waiting_for_prompt_confirmation)


@router.callback_query(F.data.startswith("card_prompt:"))
async def handle_prompt_choice(
    callback: CallbackQuery, state: FSMContext, l10n: Localization
) -> None:
    """Предложить текстовые поправки или вернуть текущий промпт без изменений."""
    await callback.answer()
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return
    message = callback.message
    async with isolation.lock(state.key):
        data = await state.get_data()
        parts = (callback.data or "").split(":")
        current = await state.get_state()
        if (
            len(parts) != 4
            or parts[1] != data.get("session_id")
            or parts[2] != data.get("prompt_revision")
            or data.get("prompt_menu_id") != message.message_id
            or (
                parts[3] == "edit"
                and current != CardStates.waiting_for_prompt_confirmation.state
            )
            or (
                parts[3] == "skip"
                and current != CardStates.waiting_for_prompt_changes.state
            )
            or parts[3] not in {"edit", "skip"}
        ):
            await message.answer(l10n.get("card_session_expired"))
            return
        if parts[3] == "skip":
            await show_prompt_review(message, state, l10n, str(data["final_prompt"]))
        else:
            token = token_hex(6)
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=l10n.get("card_prompt_skip_changes"),
                            callback_data=f"card_prompt:{parts[1]}:{token}:skip",
                        )
                    ]
                ]
            )
            request = await message.answer(
                l10n.get("card_prompt_changes_request"), reply_markup=keyboard
            )
            await state.update_data(
                prompt_revision=token, prompt_menu_id=request.message_id
            )
            await state.set_state(CardStates.waiting_for_prompt_changes)
        with suppress(TelegramAPIError):
            await message.edit_reply_markup(reply_markup=None)


@router.message(CardStates.waiting_for_prompt_changes, F.text, ~F.text.startswith("/"))
async def handle_prompt_changes(
    message: Message, state: FSMContext, l10n: Localization
) -> None:
    """Показать поправки в итоговом тексте без запроса к AI и списания токенов."""
    async with isolation.lock(state.key):
        if await state.get_state() != CardStates.waiting_for_prompt_changes.state:
            return
        data = await state.get_data()
        changes = (message.text or "").strip()
        try:
            prompt = amend_card_prompt(str(data["base_prompt"]), changes)
        except ValueError:
            await message.answer(l10n.get("card_prompt_changes_invalid"))
            return
        await state.update_data(prompt_changes=changes)
        await show_prompt_review(message, state, l10n, prompt)


@router.message(CardStates.waiting_for_prompt_changes, ~F.text)
async def handle_invalid_prompt_changes(message: Message, l10n: Localization) -> None:
    """Ожидать текст, сохраняя исходное фото и текущий промпт."""
    await message.answer(l10n.get("card_prompt_changes_invalid"))


@router.message(CardStates.waiting_for_prompt_confirmation, ~F.text.startswith("/"))
async def handle_unconfirmed_prompt(message: Message, l10n: Localization) -> None:
    """Напомнить о явном выборе действия перед генерацией."""
    await message.answer(l10n.get("card_prompt_confirmation_required"))
