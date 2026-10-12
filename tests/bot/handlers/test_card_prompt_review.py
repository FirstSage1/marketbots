"""Правки промпта до генерации: подтверждение, отмена и устаревшие кнопки."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers.card import handle_prompt_generation
from src.bot.handlers.card_prompt_review import (
    handle_invalid_prompt_changes,
    handle_prompt_changes,
    handle_prompt_choice,
    show_prompt_review,
)
from src.bot.states.card import CardStates
from src.services.card_prompts import amend_card_prompt
from src.services.product_card import ProductCardService
from tests.bot.handlers.test_card_corrections import session_factory


@pytest.fixture
def message() -> MagicMock:
    """Ответы Telegram полностью заменены моками."""
    message = MagicMock(message_id=42, text="Сделай фон зимним")
    message.answer = AsyncMock(return_value=message)
    message.edit_reply_markup = AsyncMock()
    return message


@pytest.fixture
def l10n() -> MagicMock:
    """Ключи локализации читаются без рабочего конфига."""
    l10n = MagicMock()
    l10n.get.side_effect = lambda key, **_: key
    return l10n


@pytest.fixture
async def state(message: MagicMock, l10n: MagicMock) -> FSMContext:
    """Подготовить реальный FSM с показанным исходным промптом."""
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=2, user_id=3))
    await state.set_data(
        {"session_id": "test", "base_prompt": "Фото термоса", "image_file_id": "photo"}
    )
    await show_prompt_review(message, state, l10n, "Фото термоса")
    return state


async def choose(
    action: str, state: FSMContext, message: MagicMock, l10n: MagicMock
) -> MagicMock:
    """Нажать кнопку действующей версии промпта."""
    data = await state.get_data()
    callback = MagicMock(
        message=message,
        data=f"card_prompt:test:{data['prompt_revision']}:{action}",
    )
    callback.answer = AsyncMock()
    await handle_prompt_choice(callback, state, l10n)
    return callback


async def test_edits_require_confirmation_and_replace_previous_changes(
    state: FSMContext, message: MagicMock, l10n: MagicMock
) -> None:
    """Текст только обновляет черновик; повторная правка не накапливает старый текст."""
    original = await state.get_data()
    await choose("edit", state, message, l10n)
    assert await state.get_state() == CardStates.waiting_for_prompt_changes.state
    await handle_prompt_changes(message, state, l10n)
    data = await state.get_data()
    assert data["final_prompt"] == amend_card_prompt("Фото термоса", message.text)
    assert data["prompt_revision"] != original["prompt_revision"]
    assert await state.get_state() == CardStates.waiting_for_prompt_confirmation.state
    await choose("edit", state, message, l10n)
    message.text = "Добавь лес на фоне"
    await handle_prompt_changes(message, state, l10n)
    prompt = (await state.get_data())["final_prompt"]
    assert "Добавь лес на фоне" in prompt
    assert "Сделай фон зимним" not in prompt


async def test_skip_edits_keeps_prompt_and_invalidates_previous_buttons(
    state: FSMContext, message: MagicMock, l10n: MagicMock
) -> None:
    """Передумав редактировать, пользователь получает подтверждение текущего текста."""
    old_callback = await choose("edit", state, message, l10n)
    await choose("skip", state, message, l10n)
    assert (await state.get_data())["final_prompt"] == "Фото термоса"
    assert await state.get_state() == CardStates.waiting_for_prompt_confirmation.state
    await handle_prompt_choice(old_callback, state, l10n)
    message.answer.assert_any_await("card_session_expired")
    assert await state.get_state() == CardStates.waiting_for_prompt_confirmation.state


@pytest.mark.parametrize("text", ["   ", "а" * 1501])
async def test_invalid_edits_keep_draft(
    state: FSMContext, message: MagicMock, l10n: MagicMock, text: str
) -> None:
    """Ошибочный ввод не меняет промпт и не запускает генерацию."""
    await choose("edit", state, message, l10n)
    original = await state.get_data()
    message.text = text
    await handle_prompt_changes(message, state, l10n)
    assert await state.get_data() == original
    assert await state.get_state() == CardStates.waiting_for_prompt_changes.state
    message.answer.assert_any_await("card_prompt_changes_invalid")


async def test_stale_confirmation_cannot_generate_new_draft(
    state: FSMContext, message: MagicMock, l10n: MagicMock
) -> None:
    """Кнопка старой версии не подтверждает новые пожелания автоматически."""
    data = await state.get_data()
    callback = MagicMock(
        message=message, data=f"card_generate:test:{data['prompt_revision']}"
    )
    callback.answer = AsyncMock()
    await choose("edit", state, message, l10n)
    await handle_prompt_changes(message, state, l10n)
    service = MagicMock(spec=ProductCardService)
    service.generate = AsyncMock()
    await handle_prompt_generation(callback, state, l10n, MagicMock(), service)
    service.generate.assert_not_awaited()
    message.answer.assert_any_await("card_session_expired")


async def test_nontext_edits_request_text(message: MagicMock, l10n: MagicMock) -> None:
    """Фото или стикер в шаге правок не теряют контекст диалога."""
    await handle_invalid_prompt_changes(message, l10n)
    message.answer.assert_any_await("card_prompt_changes_invalid")


async def test_confirmed_generation_receives_exact_amended_prompt(
    state: FSMContext, message: MagicMock, l10n: MagicMock
) -> None:
    """Провайдер получает показанный текст только после нажатия подтверждения."""
    await choose("edit", state, message, l10n)
    await handle_prompt_changes(message, state, l10n)
    data = await state.get_data()
    service = MagicMock(spec=ProductCardService)
    service.generate = AsyncMock()
    bot = MagicMock()
    from io import BytesIO

    bot.download = AsyncMock(return_value=BytesIO(b"reference"))
    message.delete = AsyncMock()
    callback = MagicMock(
        message=message, data=f"card_generate:test:{data['prompt_revision']}"
    )
    callback.answer = AsyncMock()

    await handle_prompt_generation(callback, state, l10n, bot, service, session_factory)

    service.generate.assert_awaited_once()
    assert service.generate.call_args.args[2] == b"reference"
    assert service.generate.call_args.args[3] == data["final_prompt"]
