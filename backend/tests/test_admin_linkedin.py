import json
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


def _sse_events(response) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_type = ""
    data = ""
    for line in response.text.splitlines() + [""]:
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
        elif not line and event_type and data:
            events.append((event_type, json.loads(data)))
            event_type = ""
            data = ""
    return events


def _mock_generation(monkeypatch, admin_linkedin, drafts: list[str | list[str]]):
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
        output = next(outputs)
        for chunk in output if isinstance(output, list) else [output]:
            yield chunk

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
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response)
    payload = next(data for event, data in events if event == "linkedin_done")
    streamed = "".join(
        data["content"] for event, data in events if event == "linkedin_delta"
    )
    assert streamed == expected
    assert payload["post"] == expected
    assert payload["character_count"] == len(expected)
    assert payload["sources"][0]["article_nums"] == ["L1222-9"]

    prepare_kwargs = prepare.await_args.kwargs
    assert prepare_kwargs["organisation_id"] == admin_linkedin._COMMON_CORPUS_ORG_ID
    assert prepare_kwargs["org_idcc_list"] is None
    assert prepare_kwargs["is_replay"] is True
    generation_kwargs = agent.stream_generate.call_args.kwargs
    assert generation_kwargs["generation_mode"] == "linkedin_post"
    assert generation_kwargs["buffer_size"] == 1
    assert "linkedin_revision" not in generation_kwargs
    assert payload["rag_trace"]["search_plan_usage"]["linkedin_empty_retry_count"] == 0


async def test_linkedin_generation_returns_non_empty_model_output_byte_for_byte(
    client, admin_user, monkeypatch
):
    """Aucune validation, réécriture, normalisation ou injection après génération."""

    from app.api import admin_linkedin

    raw_chunks = ["  **Brouillon", " brut** #RH 🚀\n\n", "Qu'en pensez-vous ?\n"]
    raw_output = "".join(raw_chunks)
    agent, _prepare = _mock_generation(monkeypatch, admin_linkedin, [raw_chunks])

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    events = _sse_events(response)
    assert [
        data["content"] for event, data in events if event == "linkedin_delta"
    ] == raw_chunks
    done = next(data for event, data in events if event == "linkedin_done")
    assert done["post"] == raw_output
    assert agent.stream_generate.call_count == 1
    assert "linkedin_revision_count" not in done["rag_trace"]["search_plan_usage"]


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
    events = _sse_events(response)
    assert "".join(
        data["content"] for event, data in events if event == "linkedin_delta"
    ) == _linkedin_post()
    done = next(data for event, data in events if event == "linkedin_done")
    assert done["rag_trace"]["search_plan_usage"]["linkedin_empty_retry_count"] == 1


async def test_linkedin_generation_keeps_partial_output_when_stream_fails(
    client, admin_user, monkeypatch
):
    from app.api import admin_linkedin

    agent, _prepare = _mock_generation(monkeypatch, admin_linkedin, ["unused"])

    async def interrupted_stream(*args, **kwargs):
        yield "Texte partiel exact."
        raise TimeoutError

    agent.stream_generate = MagicMock(side_effect=interrupted_stream)

    response = await client.post(
        "/api/v1/admin/linkedin/generate",
        json={"topic": "Le télétravail"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    events = _sse_events(response)
    assert [
        data["content"] for event, data in events if event == "linkedin_delta"
    ] == ["Texte partiel exact."]
    assert not any(event == "linkedin_done" for event, _data in events)
    error = next(data for event, data in events if event == "linkedin_error")
    assert "reste visible" in error["message"]


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


def test_linkedin_prompt_requires_exact_claim_to_source_alignment():
    from app.rag.agent import _generation_system_prompt

    prompt, _max_tokens = _generation_system_prompt("linkedin_post")

    assert "Un rapprochement de\n  mots-clés ne suffit jamais" in prompt
    assert "moyens du pourvoi, visas et simples rappels de\n  textes" in prompt
    assert (
        "l'accès d'un salarié à ses propres courriels ne\n  fonde pas l'accès de l'employeur"
    ) in prompt
    assert (
        "des documents papier trouvés dans\n"
        "  un bureau ne fondent pas à eux seuls la règle applicable aux courriels"
    ) in prompt
    assert "Une même parenthèse contient une seule autorité" in prompt
    assert "Une référence exacte apparaît au maximum une fois dans tout le" in prompt
    assert "Il n'est jamais obligatoire\n  d'utiliser tous les documents récupérés" in prompt
    assert "Une référence ne forme jamais une phrase autonome après un point" in prompt
    assert "N'invente aucun conseil opérationnel, checklist, procédure" in prompt
    assert "N'élargis jamais une formulation juridique par des mots totalisants" in prompt
    assert "Le CTA ne doit pas pouvoir recevoir seulement « oui » ou « non »" in prompt
    assert "Le hook est une phrase complète avec un verbe conjugué" in prompt
    assert "N'utilise pas la structure « Sujet : règle »" in prompt
    assert "Place l'élément décisif au début du hook" in prompt
    assert "la situation X n'empêche pas Y, sauf Z" in prompt
    assert "détermine mentalement l'intention dominante du sujet" in prompt
    assert "risque ou erreur fréquente" in prompt
    assert "délai, montant ou seuil" in prompt
    assert "décision de justice" in prompt
    assert "procédure : ouvre sur la première étape bloquante" in prompt
    assert "comparaison : expose la différence" in prompt
    assert "Le hook promet une information utile mais ne résume pas toute" in prompt
    assert "Ne place aucune référence juridique entre parenthèses dans le hook" in prompt
    assert "le hook ne dit jamais que l'acteur « perd l'accès »" in prompt
    assert "Test obligatoire pour le hook" in prompt
    assert "en principe / sauf /\n   change / encadre / limite" in prompt
    assert "La séquence « . ( » n'apparaît jamais" in prompt
    assert "Deux paragraphes consécutifs ne peuvent\n  pas avoir le même message central" in prompt
    assert "Résume mentalement chaque paragraphe en quelques mots" in prompt
    assert "Après le dernier fait juridique utile, passe directement au CTA" in prompt
    assert "L'avant-dernier paragraphe apporte un fait juridique nouveau" in prompt
    assert "Ne transforme jamais une\n  présomption" in prompt
    assert "aucune phrase ne dépasse 24 mots" in prompt
    assert "Contrôle final silencieux obligatoire avant d'émettre le premier mot" in prompt


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
