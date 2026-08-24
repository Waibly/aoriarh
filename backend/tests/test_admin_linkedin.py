from unittest.mock import AsyncMock, MagicMock

from app.rag.agent import RAGSource, RagTrace
from app.rag.search import SearchResult


def _linkedin_post() -> str:
    return (
        "Le refus du télétravail doit respecter le cadre applicable.\n\n"
        "L'article L.1222-9 du Code du travail impose de motiver le refus dans "
        "les situations prévues.\n\n"
        "Quelle méthode votre équipe utilise pour tracer la motivation des refus ?"
    )


def _source() -> RAGSource:
    return RAGSource(
        document_id="code-travail",
        document_name="Code du travail",
        source_type="code_travail",
        source_type_label="Code du travail",
        norme_niveau=2,
        excerpt="L'employeur motive son refus.",
        full_text="Texte complet",
        article_nums=["L1222-9"],
    )


def _mock_generation(monkeypatch, admin_linkedin, drafts: list[str]):
    result = MagicMock()
    trace = RagTrace(
        query_original="Peut-on refuser le télétravail ?",
        search_plan={"answer_format": "verdict_then_conditions"},
        search_plan_usage={"execution": "adaptive"},
    )
    prepare = AsyncMock(return_value=([result], "Refus du télétravail", trace))
    monkeypatch.setattr(admin_linkedin, "prepare_rag_context", prepare)

    agent = MagicMock()
    agent.format_sources.return_value = [_source()]
    outputs = iter(drafts)

    async def stream_generate(*args, **kwargs):
        yield next(outputs)

    agent.stream_generate = MagicMock(side_effect=stream_generate)
    monkeypatch.setattr(admin_linkedin, "RAGAgent", lambda: agent)
    monkeypatch.setattr(admin_linkedin.cost_tracker, "flush", AsyncMock())
    return agent, prepare


async def test_linkedin_generation_uses_common_production_pipeline(client, admin_user, monkeypatch):
    from app.api import admin_linkedin

    expected = _linkedin_post()
    agent, prepare = _mock_generation(monkeypatch, admin_linkedin, [expected])

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Peut-on refuser le télétravail ?"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["post"] == expected
    assert payload["character_count"] == len(expected)
    assert payload["sources"][0]["article_nums"] == ["L1222-9"]

    prepare_kwargs = prepare.await_args.kwargs
    assert prepare_kwargs["organisation_id"] == admin_linkedin._COMMON_CORPUS_ORG_ID
    assert prepare_kwargs["org_idcc_list"] is None
    assert prepare_kwargs["is_replay"] is True
    generation_kwargs = agent.stream_generate.call_args.kwargs
    assert generation_kwargs["generation_mode"] == "linkedin_post"
    assert "linkedin_revision" not in generation_kwargs
    assert payload["rag_trace"]["search_plan_usage"]["linkedin_empty_retry_count"] == 0


async def test_linkedin_generation_returns_non_empty_model_output_byte_for_byte(
    client, admin_user, monkeypatch
):
    """Aucune validation, réécriture, normalisation ou injection après génération."""

    from app.api import admin_linkedin

    raw_output = "  **Brouillon brut** #RH 🚀\n\nQu'en pensez-vous ?\n"
    agent, _prepare = _mock_generation(monkeypatch, admin_linkedin, [raw_output])

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert response.json()["post"] == raw_output
    assert agent.stream_generate.call_count == 1
    assert "linkedin_revision_count" not in response.json()["rag_trace"]["search_plan_usage"]


async def test_linkedin_generation_retries_one_empty_initial_response(
    client, admin_user, monkeypatch
):
    from app.api import admin_linkedin

    agent, _prepare = _mock_generation(monkeypatch, admin_linkedin, ["", _linkedin_post()])

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert agent.stream_generate.call_count == 2
    assert response.json()["rag_trace"]["search_plan_usage"]["linkedin_empty_retry_count"] == 1


async def test_linkedin_generation_is_admin_only(client, regular_user):
    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le délai de préavis"},
        headers={"Authorization": f"Bearer {regular_user['token']}"},
    )

    assert response.status_code == 403


def test_linkedin_prompt_requests_the_complete_publishable_output():
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
    assert "Les deux premières lignes visibles sont décisives" in prompt
    assert "par paragraphe par défaut" in prompt
    assert "Intègre chaque référence juridique stable dans la phrase" in prompt
    assert "Ne crée aucune section, liste, ligne ou bibliographie finale de références" in prompt
    assert "Références juridiques : C. trav." not in prompt
    assert "La sortie entière doit être publiable telle quelle" in prompt
    assert "Le serveur insérera" not in prompt
    assert "RÉVISION CONTRÔLÉE" not in prompt
    assert max_tokens == 6000


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
