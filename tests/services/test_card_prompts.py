"""Проверки индивидуальных сценариев фотографий товара."""

import pytest
from pydantic import ValidationError

from src.services.card_prompts import (
    CardAssetType,
    CardIdea,
    CardIdeas,
    Marketplace,
    amend_card_prompt,
    build_card_prompt,
    build_correction_prompt,
    build_marketplace_card_prompt,
    parse_card_options,
)


def make_ideas() -> CardIdeas:
    """Создать реалистичный ответ анализа для тестов."""
    return CardIdeas(
        product="Матовый чёрный термос, цилиндрическая форма, крышка и логотип",
        ideas=[
            CardIdea(
                title="Утро в офисе",
                scene="Термос стоит рядом с ноутбуком, человек наливает напиток утром.",
            ),
            CardIdea(
                title="Поход",
                scene="Термос закреплён в боковом кармане рюкзака на лесной тропе.",
            ),
            CardIdea(
                title="Подарок",
                scene="Термос передают в аккуратной подарочной упаковке дома.",
            ),
        ],
    )


def test_card_ideas_require_three_distinct_scenes() -> None:
    """Ответ анализа содержит ровно три разные идеи."""
    ideas = make_ideas()

    assert len(ideas.ideas) == 3
    assert len({idea.title for idea in ideas.ideas}) == 3


def test_card_ideas_reject_duplicate_scenes() -> None:
    """Повторы не превращаются в одинаковые кнопки для пользователя."""
    values = make_ideas().model_dump()
    values["ideas"][1]["title"] = values["ideas"][0]["title"]

    with pytest.raises(ValidationError):
        CardIdeas.model_validate(values)


def test_build_card_prompt_preserves_product_identity() -> None:
    """Финальный запрос закрепляет видимые детали исходного товара."""
    prompt = build_card_prompt(make_ideas(), 1)

    assert "Матовый чёрный термос" in prompt
    assert "лесной тропе" in prompt
    assert "Не заменяй товар похожим" in prompt
    assert "Без текста, коллажа" in prompt


def test_build_card_prompt_preserves_long_scene_and_product_details() -> None:
    """Детали в конце длинного описания не теряются перед генерацией."""
    product = "Описание товара " * 30 + "жёлтая молния на рукаве"
    scene = "Подробная сцена " * 30 + "руки в карманах, полный рост"
    ideas = CardIdeas(
        product=product,
        ideas=[
            CardIdea(title=f"Идея {index}", scene=f"{index}. {scene}")
            for index in range(3)
        ],
    )

    prompt = build_card_prompt(ideas, 0)

    assert product in prompt
    assert ideas.ideas[0].scene in prompt


@pytest.mark.parametrize("correction", ["покажи со спины", "а" * 1500])
def test_correction_preserves_entire_user_request(correction: str) -> None:
    """Правки, включая максимальную длину, передаются без скрытого усечения."""
    prompt = build_correction_prompt(correction)
    assert correction in prompt
    assert "Не заменяй товар похожим" in prompt


@pytest.mark.parametrize("correction", ["   ", "а" * 1501])
def test_correction_rejects_invalid_length(correction: str) -> None:
    """Неверная длина отклоняется до обращения к провайдеру."""
    with pytest.raises(ValueError, match="Длина правки"):
        build_correction_prompt(correction)


def test_amended_prompt_preserves_scene_and_prioritizes_changes() -> None:
    """Пожелания дополняют исходный товар и имеют приоритет над старой сценой."""
    base = build_card_prompt(make_ideas(), 1)
    prompt = amend_card_prompt(base, "Покажи термос зимой в городе")
    assert base in prompt
    assert "Покажи термос зимой в городе" in prompt
    assert "выполни поправки пользователя" in prompt


def test_overlong_final_prompt_is_rejected_without_truncating() -> None:
    """Текст не усекается незаметно при превышении лимита итогового сообщения."""
    with pytest.raises(ValueError, match="Итоговый промпт слишком длинный"):
        amend_card_prompt("а" * 3500, "Новый фон")


def test_build_card_prompt_rejects_invalid_index() -> None:
    """Несуществующая кнопка не должна приводить к случайному сценарию."""
    with pytest.raises(ValueError, match="Неизвестная идея"):
        build_card_prompt(make_ideas(), 3)


def test_marketplace_options_change_visual_prompt() -> None:
    """Площадка и тип изображения явно передаются в генератор."""
    prompt = build_marketplace_card_prompt(
        make_ideas(), 0, Marketplace.OZON, CardAssetType.INFOGRAPHIC
    )

    assert "OZON" in prompt
    assert "Инфографика" in prompt
    assert "свободные области" in prompt


@pytest.mark.parametrize(
    ("caption", "marketplace", "asset_type"),
    [
        (
            "WB, фото в использовании",
            Marketplace.WILDBERRIES,
            CardAssetType.LIFESTYLE,
        ),
        (
            "Яндекс Маркет, инфографика",
            Marketplace.YANDEX_MARKET,
            CardAssetType.INFOGRAPHIC,
        ),
        (None, Marketplace.UNIVERSAL, CardAssetType.COVER),
    ],
)
def test_parse_card_options_from_caption(
    caption: str | None, marketplace: Marketplace, asset_type: CardAssetType
) -> None:
    """Подпись к фото выбирает площадку и формат без отдельного диалога."""
    assert parse_card_options(caption) == (marketplace, asset_type)
