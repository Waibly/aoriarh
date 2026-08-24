from unittest.mock import AsyncMock, MagicMock

from app.rag.agent import RAGSource, RagTrace


def _valid_linkedin_body() -> str:
    sentence = (
        "Le refus du télétravail reste possible lorsque l'employeur respecte le cadre "
        "applicable et motive sa décision dans les situations prévues."
    )
    return "\n\n".join(" ".join([sentence] * 2) for _ in range(5))


async def test_linkedin_generation_uses_common_production_pipeline(client, admin_user, monkeypatch):
    from app.api import admin_linkedin

    result = MagicMock()
    trace = RagTrace(
        query_original="Peut-on refuser le télétravail ?",
        search_plan={"answer_format": "verdict_then_conditions"},
        search_plan_usage={"execution": "adaptive"},
    )
    prepare = AsyncMock(return_value=([result], "Refus du télétravail", trace))
    monkeypatch.setattr(admin_linkedin, "prepare_rag_context", prepare)

    source = RAGSource(
        document_id="code-travail",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="L'employeur motive son refus.",
        full_text="Texte complet",
        article_nums=["L1222-9"],
    )
    agent = MagicMock()
    agent.format_sources.return_value = [source]

    async def stream_generate(*args, **kwargs):
        yield _valid_linkedin_body() + " art. L1222-9."

    agent.stream_generate = MagicMock(side_effect=stream_generate)
    monkeypatch.setattr(admin_linkedin, "RAGAgent", lambda: agent)
    monkeypatch.setattr(admin_linkedin.cost_tracker, "flush", AsyncMock())

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Peut-on refuser le télétravail ?"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character_count"] == len(payload["post"])
    assert payload["character_count"] <= 3000
    assert "Références juridiques : Code du travail, art. L1222-9" in payload["post"]
    assert "#" not in payload["post"]
    assert "**" not in payload["post"]
    assert "?" not in payload["post"]
    assert payload["sources"][0]["article_nums"] == ["L1222-9"]

    prepare_kwargs = prepare.await_args.kwargs
    assert prepare_kwargs["organisation_id"] == admin_linkedin._COMMON_CORPUS_ORG_ID
    assert prepare_kwargs["org_idcc_list"] is None
    assert prepare_kwargs["is_replay"] is True
    generation_kwargs = agent.stream_generate.call_args.kwargs
    assert generation_kwargs["generation_mode"] == "linkedin_post"


async def test_linkedin_generation_is_admin_only(client, regular_user):
    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le délai de préavis"},
        headers={"Authorization": f"Bearer {regular_user['token']}"},
    )

    assert response.status_code == 403


def test_linkedin_post_limit_is_enforced_at_sentence_boundary():
    from app.api.admin_linkedin import _fit_linkedin_limit

    post = ("Une règle utile. " * 240).strip()
    fitted = _fit_linkedin_limit(post)

    assert len(fitted) <= 3000
    assert fitted.endswith("…")


def test_linkedin_prompt_never_contains_chat_instructions():
    from app.rag.agent import _generation_system_prompt

    prompt, max_tokens = _generation_system_prompt("linkedin_post")

    assert "FIABILITÉ JURIDIQUE COMMUNE" in prompt
    assert "MODE DE SORTIE — POST LINKEDIN" in prompt
    assert "Questions complémentaires" not in prompt
    assert "Tu es l'expert juridique RH intégré à l'organisation" not in prompt
    assert max_tokens == 1200


def test_linkedin_validator_rejects_chat_format_and_sanitizer_removes_markers():
    from app.api.admin_linkedin import _linkedin_draft_issues, _sanitize_linkedin_post

    draft = "## Réponse\n\n- **Une règle utile.**\n\nUne question finale ?\n\n#RH 🚀"

    issues = _linkedin_draft_issues(draft)
    cleaned = _sanitize_linkedin_post(draft)

    assert any("Markdown" in issue for issue in issues)
    assert any("question" in issue for issue in issues)
    assert any("hashtags" in issue for issue in issues)
    assert any("emojis" in issue for issue in issues)
    assert "**" not in cleaned
    assert "#" not in cleaned
    assert "🚀" not in cleaned


def test_references_only_include_stable_refs_cited_in_post():
    from app.api.admin_linkedin import _append_references

    cited = RAGSource(
        document_id="article-1",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Télétravail.",
        full_text="Télétravail.",
        article_nums=["L1222-9"],
    )
    unused = RAGSource(
        document_id="article-2",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Autre règle.",
        full_text="Autre règle.",
        article_nums=["L1234-1"],
    )

    post = _append_references(
        "La règle figure à l'art. L.1222-9 du Code du travail.",
        [cited, unused],
    )

    assert "L1222-9" in post
    assert "L1234-1" not in post


async def test_linkedin_generation_revises_one_invalid_draft(client, admin_user, monkeypatch):
    from app.api import admin_linkedin

    result = MagicMock()
    trace = RagTrace(query_original="Le télétravail")
    monkeypatch.setattr(
        admin_linkedin,
        "prepare_rag_context",
        AsyncMock(return_value=([result], "Télétravail", trace)),
    )
    source = RAGSource(
        document_id="code-travail",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Règle applicable.",
        full_text="Règle applicable.",
        article_nums=["L1222-9"],
    )
    agent = MagicMock()
    agent.format_sources.return_value = [source]
    drafts = iter(["**Réponse courte** ? #RH 🚀", _valid_linkedin_body() + " art. L1222-9."])

    async def stream_generate(*args, **kwargs):
        yield next(drafts)

    agent.stream_generate = MagicMock(side_effect=stream_generate)
    monkeypatch.setattr(admin_linkedin, "RAGAgent", lambda: agent)
    monkeypatch.setattr(admin_linkedin.cost_tracker, "flush", AsyncMock())

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert agent.stream_generate.call_count == 2
    assert agent.stream_generate.call_args.kwargs["linkedin_revision"] is True
    assert "**" not in response.json()["post"]
    assert "?" not in response.json()["post"]


async def test_linkedin_generation_returns_clean_timeout(client, admin_user, monkeypatch):
    from app.api import admin_linkedin

    monkeypatch.setattr(admin_linkedin, "RAGAgent", MagicMock)
    monkeypatch.setattr(
        admin_linkedin,
        "prepare_rag_context",
        AsyncMock(side_effect=TimeoutError),
    )

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "La recherche documentaire a expiré. Veuillez réessayer."
