"""Tests des préfiltres déterministes de l'intent router.

Le pattern « capacités » est ancré en fin de question : « que sais-tu
faire ? » doit recevoir la présentation produit, mais « que peux-tu me dire
sur le préavis ? » est une vraie question juridique qui doit partir en RAG.
"""
from __future__ import annotations

import pytest

from app.rag.intent_router import Intent, classify_intent


@pytest.mark.asyncio
class TestPrefilterCapabilities:
    async def test_que_sais_tu_faire(self):
        res = await classify_intent(
            "que sais-tu faire ?", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.META_CAPABILITIES
        assert res.static_answer is not None

    async def test_que_peux_tu_seul(self):
        res = await classify_intent(
            "Que peux-tu ?", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.META_CAPABILITIES

    async def test_que_peux_tu_me_dire_sur_sujet_juridique(self):
        """Une vraie question juridique ne doit PAS recevoir la présentation."""
        res = await classify_intent(
            "que peux-tu me dire sur le préavis de démission ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION
        assert res.static_answer is None

    async def test_que_sais_tu_du_licenciement(self):
        res = await classify_intent(
            "que sais-tu du licenciement économique ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION


@pytest.mark.asyncio
class TestPrefilterOthers:
    async def test_internals_blocked(self):
        res = await classify_intent(
            "tu utilises quoi comme IA ?", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.META_INTERNALS
        assert res.static_answer is not None

    async def test_greeting(self):
        res = await classify_intent(
            "bonjour", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.GREETING

    async def test_relance_conversationnelle_passe_en_rag(self):
        """Cas type relance en cours de conversation (classifieur sauté)."""
        res = await classify_intent(
            "Et pour les cadres ?", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION
        assert res.static_answer is None

    async def test_actualites_droit_social_passe_en_rag(self):
        res = await classify_intent(
            "Quelles sont les dernières actualités en droit social ?",
            db=None,
            llm=None,
            use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION
        assert res.static_answer is None


@pytest.mark.asyncio
class TestPrefilterScopeFrenchBranches:
    """Les branches du droit FRANÇAIS ne sont plus des motifs de refus direct.

    Une vraie question RH cite légitimement le code pénal (travail dissimulé),
    le code civil (art. 1240) ou le code de la route (chauffeur) — et le corpus
    contient ces codes. Seul le droit étranger reste refusé au préfiltre.
    """

    async def test_sanctions_penales_travail_dissimule_passe_en_rag(self):
        res = await classify_intent(
            "Quelles sanctions prévoit le code pénal en cas de travail dissimulé ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION
        assert res.static_answer is None

    async def test_article_code_civil_passe_en_rag(self):
        res = await classify_intent(
            "La responsabilité de l'employeur selon l'article 1240 du code civil ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION

    async def test_chauffeur_code_de_la_route_passe_en_rag(self):
        res = await classify_intent(
            "Puis-je licencier un chauffeur qui a perdu son permis (code de la route) ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION

    async def test_droit_penal_du_travail_passe_en_rag(self):
        res = await classify_intent(
            "Que risque l'employeur en droit pénal du travail pour prêt de main d'œuvre illicite ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.LEGAL_QUESTION

    async def test_droit_etranger_reste_refuse(self):
        res = await classify_intent(
            "tu connais le droit polynésien ?", db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.META_SCOPE
        assert res.static_answer is not None

    async def test_code_du_travail_suisse_reste_refuse(self):
        res = await classify_intent(
            "que dit le code du travail suisse sur les congés ?",
            db=None, llm=None, use_llm_fallback=False,
        )
        assert res.intent == Intent.META_SCOPE
        assert res.static_answer is not None
