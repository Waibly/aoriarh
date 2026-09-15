"""Tests du générateur X sans appel réseau."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.x_post_service import (
    X_POST_MAX_COMPLETION_TOKENS,
    X_SHORT_MAX_CHARACTERS,
    build_x_system_prompt,
    build_x_user_prompt,
    build_x_warnings,
    generate_x_post,
    split_x_posts,
)


def _llm_response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )


def test_prompts_define_the_free_x_formats_and_natural_hook() -> None:
    short = " ".join(build_x_system_prompt("short").split())
    thread = " ".join(build_x_system_prompt("thread").split())

    assert "français idiomatique" in short
    assert "immédiatement compréhensible à la première lecture" in short
    assert "slogan télégraphique" in short
    assert "jamais « En Syntec »" in short
    assert "La convention collective Syntec prévoit" in short
    assert "Évite les raccourcis de note juridique" in short
    assert "limite X de 280 caractères" in short
    assert "plafond prudent de 250 caractères" in short
    assert "Vise environ 220 caractères" in short
    assert "compte tous les caractères" in short
    assert "exactement trois posts" in thread
    assert "Ne place jamais « 1/3 », « 2/3 », « 3/3 »" in thread
    assert "X les relie nativement" in thread
    assert "plafond prudent de 250 caractères" in thread
    assert "Vérifie séparément la longueur de chacun" in thread


def test_user_prompt_delimits_source_data_and_profile() -> None:
    prompt = build_x_user_prompt(
        question="Quel préavis ?",
        answer_markdown="L'article L.1234-1 s'applique.",
        references=["Code du travail, art. L.1234-1"],
        user_profile="drh",
    )

    assert "<question_source>\nQuel préavis ?\n</question_source>" in prompt
    assert "Profil métier : DRH / Responsable RH" in prompt
    assert "- Code du travail, art. L.1234-1" in prompt


def test_warnings_report_limits_without_changing_content() -> None:
    short = "x" * (X_SHORT_MAX_CHARACTERS + 1)
    thread = "a" * 281 + "\n\nCourt\n\nFin"

    assert "sans troncature" in build_x_warnings(short, "short")[0]
    assert "posts 1" in build_x_warnings(thread, "thread")[0]
    assert "sans reconstruction" in build_x_warnings("Post libre", "thread")[0]


def test_posts_are_split_without_numbering_or_rewriting() -> None:
    raw = "Premier post exact.\n\nDeuxième post exact.\n\nTroisième post exact."

    assert split_x_posts(raw, "thread") == [
        "Premier post exact.",
        "Deuxième post exact.",
        "Troisième post exact.",
    ]
    assert split_x_posts("  Post court exact.  ", "short") == [
        "  Post court exact.  "
    ]


@pytest.mark.asyncio
async def test_generation_returns_non_empty_output_exactly() -> None:
    raw = "Hook naturel.\n\nRègle utile.\n\nSource exacte."
    with patch(
        "app.services.x_post_service._llm.chat.completions.create",
        new=AsyncMock(return_value=_llm_response(raw)),
    ) as create:
        generation = await generate_x_post(
            question="Question",
            answer_markdown="Réponse",
            sources=[],
            format="thread",
        )

    assert generation.content == raw
    assert generation.posts == ["Hook naturel.", "Règle utile.", "Source exacte."]
    assert generation.format == "thread"
    assert create.await_args.kwargs["reasoning_effort"] == "medium"
    assert (
        create.await_args.kwargs["max_completion_tokens"]
        == X_POST_MAX_COMPLETION_TOKENS
        == 6000
    )


@pytest.mark.asyncio
async def test_generation_retries_only_an_empty_output() -> None:
    raw = "Post court conservé"
    with patch(
        "app.services.x_post_service._llm.chat.completions.create",
        new=AsyncMock(side_effect=[_llm_response(""), _llm_response(raw)]),
    ) as create:
        generation = await generate_x_post(
            question="Question",
            answer_markdown="Réponse",
            sources=[],
            format="short",
        )

    assert generation.content == raw
    assert create.await_count == 2
