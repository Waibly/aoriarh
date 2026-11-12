"""Liste des conventions proposées, relue depuis KALI.

KALI /list/conventions liste des TEXTES (pages à partir de 1) ; chaque
convention est ensuite lue dans son conteneur pour son titre, son statut
d'extension et la présence d'au moins un texte en vigueur.
"""

from __future__ import annotations

import pytest

from app.models.ccn import CcnReference
from app.services import kali_service as kali_module
from app.services.kali_service import KaliService
from tests.conftest import test_session_factory as session_factory


def _text(idcc: str, container: str) -> dict:
    return {"id": f"KALITEXT{idcc}", "idcc": idcc, "cidConteneur": container}


def _container(titre: str, base_etat: str, attached_etat: str = "VIGUEUR_ETEN") -> dict:
    return {
        "titre": f"{titre}  ",
        "sections": [
            {"id": "KALITEXT1", "etat": base_etat, "title": f"Texte de base : {titre}"},
            {
                "id": None,
                "etat": "VIGUEUR",
                "title": "Textes Attachés",
                "sections": [{"id": "KALITEXT2", "etat": attached_etat, "title": "Accord"}],
            },
        ],
    }


CONTAINERS = {
    # Existing row seeded as extended: KALI says non-extended.
    "KALICONT2704": _container(
        "Convention collective du personnel des banques de la Guadeloupe", "VIGUEUR_NON_ETEN"
    ),
    # New non-extended convention.
    "KALICONT9001": _container(
        "Convention collective régionale du commerce (La Réunion)", "VIGUEUR_NON_ETEN"
    ),
    # Empty container: nothing in force, never offered.
    "KALICONT9002": _container("Convention abrogée", "ABROGE", attached_etat="ABROGE"),
}


# Texts by status, in publication order. KALI serves only the first
# _LIST_WINDOW results of a query: later pages repeat the last one.
TEXTS = {
    "VIGUEUR_ETEN": [
        _text("2704", "KALICONT2704"),
        {**_text("2704", "KALICONT2704"), "id": "KALITEXT2704b"},
        _text("9002", "KALICONT9002"),
        _text("", "KALICONT0000"),
    ],
    "VIGUEUR_NON_ETEN": [_text("9001", "KALICONT9001")],
    "VIGUEUR": [],
}


@pytest.fixture
def fake_kali(monkeypatch):
    calls: list[tuple[str, dict]] = []
    page_size, window = 1, 2

    async def api_post(self, client, path, json_body):
        calls.append((path, json_body))
        if path == "/list/conventions":
            (status,) = json_body["legalStatus"]
            texts = TEXTS[status]
            if json_body["sort"] == "DATE_PUBLI_DESC":
                texts = texts[::-1]
            texts = texts[:window]
            page = min(json_body["pageNumber"], max(1, window // page_size))
            start = (page - 1) * page_size
            return {
                "totalResultNumber": len(TEXTS[status]),
                "results": texts[start : start + page_size],
            }
        return CONTAINERS.get(json_body["id"])

    monkeypatch.setattr(KaliService, "_api_post", api_post)
    monkeypatch.setattr(kali_module, "_API_THROTTLE", 0)
    monkeypatch.setattr(kali_module, "_LIST_PAGE_SIZE", page_size)
    monkeypatch.setattr(kali_module, "_LIST_WINDOW", window)
    service = KaliService()
    service._client_id = service._client_secret = "x"
    return service, calls


@pytest.mark.asyncio
async def test_refresh_adds_non_extended_conventions_and_fixes_status(fake_kali):
    service, calls = fake_kali

    async with session_factory() as db:
        db.add(
            CcnReference(
                idcc="2704",
                titre="Ancien titre",
                titre_court="Banque : personnel des banques (Guadeloupe)",
                kali_id="KALICONT2704",
                etat="VIGUEUR_ETEN",
            )
        )
        await db.commit()

        result = await service.refresh_ccn_reference(db)

        banks = await db.get(CcnReference, "2704")
        reunion = await db.get(CcnReference, "9001")
        empty = await db.get(CcnReference, "9002")

    # Every page from 1; the 4 extended texts exceed the window of 2 and are
    # read from both ends.
    listed = [
        (body["legalStatus"][0], body["sort"], body["pageNumber"])
        for path, body in calls
        if path == "/list/conventions"
    ]
    assert ("VIGUEUR_ETEN", "DATE_PUBLI_DESC", 2) in listed
    assert all(page in (1, 2) for _, _, page in listed)
    assert result.listed_texts == 5
    assert banks.etat == "VIGUEUR_NON_ETEN"
    assert banks.titre == "Convention collective du personnel des banques de la Guadeloupe"
    assert banks.titre_court == "Banque : personnel des banques (Guadeloupe)"
    assert reunion is not None and reunion.etat == "VIGUEUR_NON_ETEN"
    assert reunion.kali_id == "KALICONT9001"
    assert empty is None
    assert (result.created, result.updated, result.not_installable) == (1, 1, 1)


@pytest.mark.asyncio
async def test_listing_failure_writes_nothing(monkeypatch):
    async def api_post(self, client, path, json_body):
        return None

    monkeypatch.setattr(KaliService, "_api_post", api_post)
    service = KaliService()
    service._client_id = service._client_secret = "x"
    async with session_factory() as db:
        with pytest.raises(RuntimeError):
            await service.refresh_ccn_reference(db)
