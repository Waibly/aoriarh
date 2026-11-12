"""Accords régionaux d'une CCN nationale filtrés selon le lieu d'implantation.

Une convention nationale embarque des accords propres à un territoire
(« Martinique Accord … valeur du point », « prime de vie chère (Guadeloupe) »).
Une entreprise de métropole ne doit pas les recevoir ; une entreprise de ce
territoire doit les garder, avec le reste de sa convention.
"""

from __future__ import annotations

import asyncio
import contextvars

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.access_filter import (
    build_org_access_filter,
    current_territoire,
    set_current_territoire,
)
from app.services.territoire import instrument_territoires, territoires_from_title

ORG = "11111111-1111-1111-1111-111111111111"
CCN = "convention_collective_nationale"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Martinique Accord du 19 août 2009 relatif à la prime de vie chère", ["martinique"]),
        (
            "Accord du 3 novembre 2005 relatif à la prime de vie chère 2005 (Guadeloupe)",
            ["guadeloupe"],
        ),
        ("La Réunion Accord du 14 mars 2025 relatif à la valeur du point", ["la_reunion"]),
        ("Avenant n° 117 relatif au champ géographique (La Réunion)", ["la_reunion"]),
        ("Accord du 19 février 2015 relatif à l'organisation des réunions paritaires", []),
        ("Accord relatif à la préparation de la réunion paritaire", []),
        ("Avenant du 6 juillet 2022 relatif à la participation aux réunions paritaires", []),
        ("Accord relatif aux salaires minima au 1er janvier 2026", []),
        ("Accord portant extension au département de la Guyane", ["guyane"]),
        ("Accord régional (Saint-Martin-d'Hères)", []),
        (
            "Accord relatif à l'application de la convention dans les DOM",
            [
                "guadeloupe",
                "guyane",
                "la_reunion",
                "martinique",
                "mayotte",
                "saint_barthelemy",
                "saint_martin",
                "saint_pierre_miquelon",
            ],
        ),
    ],
)
def test_territory_is_read_from_the_instrument_title(title, expected):
    assert territoires_from_title(title) == expected


def test_a_territorial_convention_is_never_restricted():
    # Choisie par l'entreprise : tous ses textes restent visibles.
    assert (
        instrument_territoires(
            "Avenant du 2 mars 2020 relatif aux salaires (Guadeloupe)",
            "CCN Personnel des banques de la Guadeloupe, de Saint-Martin et de "
            "Saint-Barthélemy (IDCC 2704)",
        )
        == []
    )
    assert instrument_territoires(
        "Martinique Accord relatif à la valeur du point", "CCN Pharmacie d'officine (IDCC 1996)"
    ) == ["martinique"]


@pytest.fixture
def corpus() -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection("t", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    points = [
        ("ccn-national", {"source_type": CCN, "idcc": "1408"}),
        ("ccn-martinique", {"source_type": CCN, "idcc": "1408", "territoires": ["martinique"]}),
        (
            "ccn-antilles",
            {"source_type": CCN, "idcc": "1408", "territoires": ["guadeloupe", "martinique"]},
        ),
        ("ccn-other-idcc", {"source_type": CCN, "idcc": "9999"}),
        ("code", {"source_type": "code_travail"}),
        # Copie de CCN propre à l'organisation (ancienne installation).
        (
            "own-ccn-martinique",
            {"source_type": CCN, "idcc": "1408", "territoires": ["martinique"], "org": ORG},
        ),
    ]
    client.upsert(
        "t",
        [
            PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={
                    "name": name,
                    "organisation_id": payload.pop("org", "common"),
                    **payload,
                },
            )
            for i, (name, payload) in enumerate(points, start=1)
        ],
    )
    return client


def _visible(client: QdrantClient, **kwargs) -> set[str]:
    f = build_org_access_filter(ORG, ["1408"], **kwargs)
    points, _ = client.scroll("t", scroll_filter=f, limit=100)
    return {p.payload["name"] for p in points}


def test_metropole_does_not_receive_regional_agreements(corpus):
    assert _visible(corpus, territoire="metropole") == {"ccn-national", "code"}
    assert _visible(corpus, territoire="alsace_moselle") == {"ccn-national", "code"}


def test_overseas_organisation_keeps_its_own_agreements_only(corpus):
    assert _visible(corpus, territoire="martinique") == {
        "ccn-national",
        "ccn-martinique",
        "ccn-antilles",
        "code",
        "own-ccn-martinique",
    }
    assert _visible(corpus, territoire="guadeloupe") == {"ccn-national", "ccn-antilles", "code"}
    assert _visible(corpus, territoire="la_reunion") == {"ccn-national", "code"}


def test_unknown_territory_keeps_previous_behaviour(corpus):
    ctx = contextvars.copy_context()
    ctx.run(set_current_territoire, None)
    assert ctx.run(_visible, corpus) == {
        "ccn-national",
        "ccn-martinique",
        "ccn-antilles",
        "code",
        "own-ccn-martinique",
    }


def test_preparation_territory_reaches_threaded_searches(corpus):
    async def scenario() -> set[str]:
        # prepare_context reçoit le libellé du contexte d'organisation.
        set_current_territoire("France métropolitaine")
        assert current_territoire.get() == "metropole"
        return await asyncio.to_thread(_visible, corpus)

    ctx = contextvars.copy_context()
    assert ctx.run(asyncio.run, scenario()) == {"ccn-national", "code"}
