"""Profile/context wiring contracts; no generation or editorial evaluation."""

import uuid

import pytest

from app.models.ccn import CcnReference, OrganisationConvention
from app.models.organisation import Organisation
from app.rag.agent import RAGAgent
from app.schemas.user import ProfilMetier
from app.services.linkedin_post_service import (
    build_linkedin_carousel_user_prompt,
    build_linkedin_user_prompt,
)
from app.services.organisation_context_service import load_organisation_context
from app.services.x_post_service import build_x_user_prompt
from tests.conftest import test_session_factory as db_session_factory


@pytest.mark.parametrize("profile", ["comptable_paie", "expert_comptable"])
def test_accounting_profile_reaches_chat_and_all_publication_prompts(profile):
    label = RAGAgent._PROFIL_METIER_LABELS[ProfilMetier(profile).value]
    agent = object.__new__(RAGAgent)
    context = agent._build_org_context_block({
        "nom": "Entreprise cliente", "profil_metier": profile,
    })
    assert f"**Profil de l'utilisateur** : {label}" in context
    assert RAGAgent._PROFIL_METIER_INSTRUCTIONS[profile] in context
    raw_answer = "  Réponse source exacte.\n\nAvec ses réserves.  "
    for builder in (
        build_linkedin_user_prompt, build_linkedin_carousel_user_prompt, build_x_user_prompt,
    ):
        kwargs = {"carousel_content": "<main>Original</main>"} if (
            builder is build_linkedin_carousel_user_prompt
        ) else {}
        prompt = builder(
            question="Question", answer_markdown=raw_answer,
            references=[], user_profile=profile, **kwargs,
        )
        assert f"Profil métier : {label}" in prompt
        assert f"<reponse_source>\n{raw_answer}\n</reponse_source>" in prompt


async def test_accountant_context_uses_each_selected_clients_convention():
    """The personal profession must never replace the selected client's IDCC."""
    async with db_session_factory() as db:
        client_ids = []
        for name, idcc in (("Client conseil", "1486"), ("Client restaurant", "1979")):
            org = Organisation(id=uuid.uuid4(), name=name, taille="11-19")
            db.add(org)
            db.add(CcnReference(idcc=idcc, titre=name + " convention"))
            await db.flush()
            db.add(OrganisationConvention(
                organisation_id=org.id, idcc=idcc, status="ready", use_custom=False,
            ))
            client_ids.append((org.id, name, idcc))
        await db.commit()
        agent = object.__new__(RAGAgent)
        for org_id, name, idcc in client_ids:
            context = await load_organisation_context(db, org_id)
            context["profil_metier"] = "expert_comptable"
            block = agent._build_org_context_block(context)
            assert f"Entreprise concernée par la conversation : {name}" in block
            assert f"IDCC {idcc}" in block
            other_idcc = "1979" if idcc == "1486" else "1486"
            assert f"IDCC {other_idcc}" not in block
