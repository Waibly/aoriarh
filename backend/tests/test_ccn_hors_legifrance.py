"""Conventions absentes de Légifrance (BTP de La Réunion : 0627, 0771, 2389).

Leur texte est rangé dans app/reference/ccn_hors_legifrance/ et doit suivre le même
chemin qu'une convention KALI : installation, synchronisation, recherche.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import select

from app.models.ccn import CcnReference, OrganisationConvention
from app.models.document import Document
from app.models.organisation import Organisation
from app.services import kali_service as kali_module
from app.services.ccn_hors_legifrance import (
    hors_legifrance_articles,
    hors_legifrance_idcc,
    reference_rows,
)
from app.services.kali_service import KaliService
from app.services.territoire import document_territoires, instrument_territoires
from tests.conftest import test_session_factory as session_factory

BTP_REUNION = {"0627", "0771", "2389"}


def test_registry_lists_the_three_btp_reunion_conventions():
    assert hors_legifrance_idcc() == BTP_REUNION


@pytest.mark.parametrize("idcc", sorted(BTP_REUNION))
def test_articles_have_kali_shape_and_a_base_text(idcc):
    articles, source_date = hors_legifrance_articles(idcc)
    assert source_date
    base = [a for a in articles if a["category"] == "base"]
    assert base, "texte de base manquant"
    # L'article 1 du texte de base fixe le champ d'application : La Réunion.
    first = next(a for a in base if a["num"] == "1")
    assert "union" in first["content"].lower()  # « Réunion » / « REUNION »
    for article in articles:
        assert article["content"].strip()
        assert article["instrument_id"] and article["instrument_title"]
        assert article["category"] in {"base", "annexe", "accord", "salaire"}
    # Chaque article reste identifiable une fois tous les textes réunis.
    assert len({a["article_id"] for a in articles}) == len(articles)
    # Le lecteur voit d'où vient un texte non officiel.
    assert all("source" in a["instrument_title"] for a in base)


def test_ouvriers_holiday_article_names_20_december():
    articles, _ = hors_legifrance_articles("2389")
    jours_feries = next(a for a in articles if a["category"] == "base" and a["num"] == "21")
    assert "20 Décembre" in jours_feries["content"]


def test_migration_rows_match_the_data_files():
    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    path = versions / "s8horsleg01_ccn_btp_reunion.py"
    spec = importlib.util.spec_from_file_location("s8horsleg01", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert {(idcc, titre, court) for idcc, titre, court in migration._ROWS} == {
        (r["idcc"], r["titre"], r["titre_court"]) for r in reference_rows()
    }


def test_a_territorial_convention_is_never_restricted_to_its_territory():
    """Une entreprise a choisi cette convention : ses textes ne sont pas filtrés."""
    for row in reference_rows():
        for article in hors_legifrance_articles(row["idcc"])[0]:
            assert instrument_territoires(article["instrument_title"], row["titre"]) == []
        doc_name = f"CCN {row['titre_court']} (IDCC {row['idcc']})"
        assert document_territoires(doc_name, row["titre"]) == []


async def test_fetch_reads_files_without_calling_legifrance(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Légifrance ne doit pas être appelé")

    monkeypatch.setattr(httpx, "AsyncClient", no_network)
    ref = CcnReference(idcc="2389", titre="Ouvriers BTP Réunion", kali_id=None)
    articles, errors, source_date = await KaliService()._fetch_kali_articles(ref)
    assert articles and errors == [] and source_date


async def test_install_creates_shared_documents_without_kali_id(monkeypatch):
    monkeypatch.setattr(kali_module, "enqueue_ingestion", AsyncMock())
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: Mock())
    row = next(r for r in reference_rows() if r["idcc"] == "2389")
    async with session_factory() as db:
        org = Organisation(name="BTP Réunion")
        db.add(org)
        db.add(CcnReference(**row, kali_id=None))
        await db.flush()
        org_conv = OrganisationConvention(organisation_id=org.id, idcc="2389", status="pending")
        db.add(org_conv)
        await db.commit()

        result = await KaliService().install_convention(db, org_conv, user_id=None)

        assert result.errors == 0, result.error_messages
        assert org_conv.status == "ready"
        names = {
            d.name
            for d in (
                await db.execute(select(Document).where(Document.organisation_id.is_(None)))
            ).scalars()
        }
        assert "CCN BTP ouvriers de La Réunion (IDCC 2389)" in names
        assert "CCN BTP ouvriers de La Réunion (IDCC 2389) — Avenants et annexes" in names


async def test_weekly_sync_keeps_an_unchanged_snapshot(monkeypatch):
    monkeypatch.setattr(kali_module, "enqueue_ingestion", AsyncMock())
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: Mock())
    monkeypatch.setattr(KaliService, "_enqueue_old_docs_cleanup", AsyncMock())
    service = KaliService()
    row = next(r for r in reference_rows() if r["idcc"] == "0771")
    async with session_factory() as db:
        db.add(CcnReference(**row, kali_id=None))
        await db.commit()
        first = await service.refresh_common_ccn(db, "0771", user_id=None)
        assert first.error is None and first.update_needed
        second = await service.refresh_common_ccn(db, "0771", user_id=None)
        assert second.error is None and not second.update_needed
