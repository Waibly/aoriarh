"""Lieu d'implantation : stockage, contexte transmis au moteur, consignes."""

import uuid

import pytest
from httpx import AsyncClient

from app.rag.agent import RAGAgent
from app.rag.reranker import build_rerank_query
from app.services.organisation_context_service import load_organisation_context
from app.services.territoire import (
    Territoire,
    parse_territoire,
    territoire_instruction,
    territoire_label,
)
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


@pytest.mark.asyncio
async def test_territoire_defaults_to_metropole_and_is_never_emptied(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    headers = auth_header(manager_user["token"])
    res = await client.post("/api/v1/organisations/", json={"name": "Métro"}, headers=headers)
    assert res.status_code == 201
    org_id = res.json()["id"]
    assert res.json()["territoire"] == "metropole"

    res = await client.patch(
        f"/api/v1/organisations/{org_id}", json={"territoire": "la_reunion"}, headers=headers
    )
    assert res.status_code == 200
    assert res.json()["territoire"] == "la_reunion"

    # Un null explicite ne vide pas le champ obligatoire.
    res = await client.patch(
        f"/api/v1/organisations/{org_id}", json={"territoire": None}, headers=headers
    )
    assert res.status_code == 200
    assert res.json()["territoire"] == "la_reunion"

    res = await client.patch(
        f"/api/v1/organisations/{org_id}", json={"territoire": "atlantide"}, headers=headers
    )
    assert res.status_code == 422

    async with session_factory() as db:
        context = await load_organisation_context(db, uuid.UUID(org_id))
    assert context is not None
    assert context["territoire"] == "La Réunion"


@pytest.mark.asyncio
async def test_create_with_territoire(client: AsyncClient, manager_user: dict[str, str]) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Strasbourg SAS", "territoire": "alsace_moselle"},
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 201
    assert res.json()["territoire"] == "alsace_moselle"


def test_parse_accepts_code_and_label_and_falls_back_to_metropole():
    assert parse_territoire("la_reunion") is Territoire.LA_REUNION
    assert parse_territoire("La Réunion") is Territoire.LA_REUNION
    assert parse_territoire(None) is Territoire.METROPOLE
    assert parse_territoire("inconnu") is Territoire.METROPOLE
    assert territoire_label("mayotte") == "Mayotte"


def test_instructions_by_territory_group():
    assert territoire_instruction("metropole") is None
    assert "droit local d'Alsace-Moselle" in territoire_instruction("alsace_moselle")
    reunion = territoire_instruction("La Réunion")
    assert "La Réunion (outre-mer)" in reunion
    assert "LODEOM" in reunion
    assert "champ d'application territorial" in reunion
    assert "SMIC propre" not in reunion
    assert "SMIC propre" in territoire_instruction("mayotte")
    caledonie = territoire_instruction("nouvelle_caledonie")
    assert "ne s'y applique pas" in caledonie


def test_org_context_block_carries_territory():
    agent = object.__new__(RAGAgent)
    reunion = agent._build_org_context_block({"nom": "Cilam", "territoire": "La Réunion"})
    assert "- Lieu d'implantation : La Réunion" in reunion
    assert "**Territoire** :" in reunion

    metro = agent._build_org_context_block({"nom": "Dupont", "territoire": "France métropolitaine"})
    assert "- Lieu d'implantation : France métropolitaine" in metro
    assert "**Territoire** :" not in metro


def test_rerank_query_exposes_territory():
    query = build_rerank_query("Le 20 décembre est-il férié ?", {"territoire": "La Réunion"}, "")
    assert "La Réunion" in query
