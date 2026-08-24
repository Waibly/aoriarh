from unittest.mock import AsyncMock, MagicMock

from app.rag.agent import RAGSource, RagTrace
from app.rag.search import SearchResult


def _valid_linkedin_body() -> str:
    sentence = (
        "Selon l'art. L1222-9 du Code du travail, le refus du télétravail reste "
        "possible lorsque l'employeur respecte le cadre applicable et motive sa "
        "décision dans les situations prévues."
    )
    body = "\n\n".join(" ".join([sentence] * 2) for _ in range(5))
    return body + "\n\nQuelle méthode votre équipe utilise pour tracer la motivation des refus ?"


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
        yield _valid_linkedin_body()

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
    assert "Références juridiques : C. trav., art. L.1222-9" in payload["post"]
    assert "#" not in payload["post"]
    assert "**" not in payload["post"]
    assert payload["post"].count("?") == 1
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


def test_linkedin_post_over_limit_is_rejected_without_truncation():
    from app.api.admin_linkedin import _linkedin_draft_issues

    post = ("Une règle utile. " * 240).strip()
    issues = _linkedin_draft_issues(post)

    assert any("dépasse" in issue for issue in issues)
    assert not post.endswith("…")


def test_linkedin_prompt_never_contains_chat_instructions():
    from app.rag.agent import _generation_system_prompt

    prompt, max_tokens = _generation_system_prompt("linkedin_post")

    assert "FIABILITÉ JURIDIQUE COMMUNE" in prompt
    assert "MODE DE SORTIE — POST LINKEDIN" in prompt
    assert "Questions complémentaires" not in prompt
    assert "Tu es l'expert juridique RH intégré à l'organisation" not in prompt
    assert "une question ouverte, précise" in prompt
    assert "puces de texte brut" in prompt
    assert "Aucun superlatif" in prompt
    assert "Le post n'est pas une réponse de chat" in prompt
    assert "au maximum quatre sources centrales" in prompt
    assert "sans modifier ton texte" in prompt
    assert max_tokens == 1200


def test_linkedin_validator_rejects_chat_format_without_sanitizing_it():
    from app.api.admin_linkedin import _linkedin_draft_issues

    draft = "## Réponse\n\n- **Une règle utile.**\n\nUne question finale ?\n\n#RH 🚀"

    issues = _linkedin_draft_issues(draft)

    assert any("Markdown" in issue for issue in issues)
    assert any("CTA" in issue for issue in issues)
    assert any("hashtags" in issue for issue in issues)
    assert any("emojis" in issue for issue in issues)
    assert "**" in draft
    assert "#" in draft
    assert "🚀" in draft


def test_linkedin_plain_text_bullets_and_numbered_steps_are_allowed():
    from app.api.admin_linkedin import _linkedin_draft_issues

    draft = "Points de contrôle :\n\n• Vérifier la règle.\n• Tracer la décision.\n\n1. Lire le texte.\n2. Appliquer la règle."

    issues = _linkedin_draft_issues(draft)

    assert not any("Markdown" in issue for issue in issues)


def test_linkedin_validator_rejects_hype_and_empty_adverbs():
    from app.api.admin_linkedin import _linkedin_draft_issues

    issues = _linkedin_draft_issues(
        "D'abord, une règle absolument incontournable, clairement meilleure et vraiment utile."
    )

    assert any("superlatifs" in issue for issue in issues)


def test_linkedin_validator_rejects_rhetorical_labels_and_abstract_wording():
    from app.api.admin_linkedin import _linkedin_draft_issues

    issues = _linkedin_draft_issues(
        "Une règle précise.\n\nAutre vigilance : ce levier stratégique n'est pas "
        "un automatisme et exige un calcul robuste."
    )

    assert any("automatisme rhétorique" in issue for issue in issues)
    assert any("abstraites ou promotionnelles" in issue for issue in issues)


def test_linkedin_validator_rejects_meta_discourse_and_vague_adverbs():
    from app.api.admin_linkedin import _linkedin_draft_issues

    issues = _linkedin_draft_issues(
        "Une règle précise. En pratique, elle crée souvent un risque. La question "
        "devient donc documentaire : le calcul doit être strictement vérifié."
    )

    assert any("méta-discours" in issue for issue in issues)
    assert any("adverbes inutiles" in issue for issue in issues)


def test_linkedin_validator_accepts_one_precise_final_cta():
    from app.api.admin_linkedin import _linkedin_draft_issues

    issues = _linkedin_draft_issues(_valid_linkedin_body())

    assert not any("CTA" in issue for issue in issues)


def test_linkedin_validator_rejects_generic_or_missing_cta():
    from app.api.admin_linkedin import _linkedin_draft_issues

    generic_issues = _linkedin_draft_issues(
        _valid_linkedin_body().rsplit("\n\n", 1)[0] + "\n\nQu'en pensez-vous ?"
    )
    missing_issues = _linkedin_draft_issues(_valid_linkedin_body().rsplit("\n\n", 1)[0])

    assert any("générique" in issue for issue in generic_issues)
    assert any("CTA" in issue for issue in missing_issues)


def test_linkedin_validator_rejects_subject_verb_inversion():
    from app.api.admin_linkedin import _linkedin_draft_issues

    issues = _linkedin_draft_issues(
        _valid_linkedin_body().rsplit("\n\n", 1)[0]
        + "\n\nQuels critères utilisez-vous pour motiver un refus ?"
    )

    assert any("inversion sujet-verbe" in issue for issue in issues)


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
        "La règle figure à l'art. L.1222-9 du Code du travail.\n\n"
        "Comment votre équipe trace cette règle ?",
        [cited, unused],
    )

    assert "L.1222-9" in post
    assert "L.1234-1" not in post


def test_reference_line_only_includes_articles_cited_in_post():
    from app.api.admin_linkedin import _append_references

    source = RAGSource(
        document_id="code-travail",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Deux articles présents dans le même document.",
        full_text="Deux articles présents dans le même document.",
        article_nums=["L1222-9", "L1234-1"],
    )

    post = _append_references(
        "La règle appliquée figure à l'art. L.1222-9 du Code du travail.\n\n"
        "Comment votre équipe trace cette décision ?",
        [source],
    )

    assert "Références juridiques : C. trav., art. L.1222-9" in post
    assert "L.1234-1" not in post


def test_reference_line_uses_canonical_jurisprudence_metadata_once():
    from app.api.admin_linkedin import _build_reference_line

    source = RAGSource(
        document_id="decision-1",
        document_name="Cass. Chambre sociale, 11/10/2023, n° 22-14.682",
        source_type="arret_cour_cassation",
        source_type_label="Arrêt Cour de cassation",
        norme_niveau=4,
        excerpt="Décision.",
        full_text="Décision.",
        juridiction="Cour de cassation",
        chambre="Chambre sociale",
        numero_pourvoi="22-14.682",
        date_decision="2023-10-11",
    )

    line = _build_reference_line([source])

    assert line == "Références juridiques : Cass. soc., 11 octobre 2023, n° 22-14.682"
    assert line.count("22-14.682") == 1
    assert "2023-10-11" not in line


def test_references_are_inserted_before_the_final_cta():
    from app.api.admin_linkedin import _append_references

    source = RAGSource(
        document_id="article-1",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Télétravail.",
        full_text="Télétravail.",
        article_nums=["L1222-9"],
    )
    cta = "Quelle méthode votre équipe utilise pour tracer ses refus ?"

    post = _append_references(
        f"La règle figure à l'art. L1222-9 du Code du travail.\n\n{cta}",
        [source],
    )

    assert post.endswith(cta)
    assert post.index("Références juridiques") < post.index(cta)
    assert post.replace("\n\nRéférences juridiques : C. trav., art. L.1222-9", "") == (
        f"La règle figure à l'art. L1222-9 du Code du travail.\n\n{cta}"
    )


def test_linkedin_validator_rejects_reference_absent_from_documents():
    from app.api.admin_linkedin import _linkedin_draft_issues

    source = RAGSource(
        document_id="article-1",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Télétravail.",
        full_text="Télétravail.",
        article_nums=["L1222-9"],
    )
    draft = _valid_linkedin_body().replace("L1222-9", "L9999-1")

    issues = _linkedin_draft_issues(draft, [source])

    assert any("absentes des documents" in issue for issue in issues)


def test_linkedin_validator_requires_primary_rule_in_first_two_paragraphs():
    from app.api.admin_linkedin import _linkedin_draft_issues

    source = RAGSource(
        document_id="article-1",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="Télétravail.",
        full_text="Télétravail.",
        article_nums=["L1222-9"],
    )
    paragraphs = _valid_linkedin_body().split("\n\n")
    paragraphs[0] = paragraphs[0].replace("L1222-9", "le cadre applicable")
    paragraphs[1] = paragraphs[1].replace("L1222-9", "le cadre applicable")

    issues = _linkedin_draft_issues("\n\n".join(paragraphs), [source])

    assert any("source prioritaire" in issue for issue in issues)


def test_linkedin_editorial_selection_prioritizes_written_law_and_caps_case_law():
    from app.api.admin_linkedin import _select_linkedin_editorial_results

    def result(document_id: str, source_type: str, index: int) -> SearchResult:
        return SearchResult(
            text=document_id,
            doc_name=document_id,
            document_id=document_id,
            source_type=source_type,
            norme_niveau=4 if source_type.startswith("arret_") else 3,
            norme_poids=0.9,
            chunk_index=index,
            score=0.9 - index / 100,
        )

    results = [
        result("juris-1", "arret_cour_cassation", 0),
        result("juris-2", "arret_cour_cassation", 1),
        result("juris-3", "arret_cour_cassation", 2),
        result("code-1", "code_travail", 3),
        result("code-2", "code_civil", 4),
        result("boss-1", "boss", 5),
    ]

    selected = _select_linkedin_editorial_results(results)
    selected_ids = list(dict.fromkeys(item.document_id for item in selected))

    assert selected_ids == ["code-1", "code-2", "boss-1", "juris-1", "juris-2"]


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
    drafts = iter(["**Réponse courte** ? #RH 🚀", _valid_linkedin_body()])

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
    assert response.json()["post"].count("?") == 1


async def test_linkedin_generation_allows_two_bounded_llm_revisions(
    client, admin_user, monkeypatch
):
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
    drafts = iter(
        [
            "**Réponse courte** ? #RH 🚀",
            "Une règle très utile, mais encore trop courte ?",
            _valid_linkedin_body(),
        ]
    )

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
    assert agent.stream_generate.call_count == 3
    assert response.json()["rag_trace"]["search_plan_usage"]["linkedin_revision_count"] == 2


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
