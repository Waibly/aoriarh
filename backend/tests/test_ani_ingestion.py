"""Tests de l'ingestion des ANI (accords nationaux interprofessionnels) via KALI.

Couvre le parsing des dates depuis le titre, le filtre de périmètre
(état / année), le payload de recherche et le formatage Markdown. Les appels
réseau (search / consult) ne sont pas testés ici — la sonde live les a validés.
"""

from datetime import date

from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.services.kali_service import KaliService

_ANI_2023 = (
    "Accord national interprofessionnel du 5 octobre 2023 relatif à la "
    "retraite complémentaire Agirc-Arrco"
)
_ANI_1ER = "Accord national interprofessionnel du 1er avril 2020 relatif à X"
_AVENANT_2009 = (
    "Avenant du 19 juin 2009 relatif à la mise en conformité avec l'accord "
    "national interprofessionnel du 11 janvier 2008"
)


def test_type_ani_present_dans_hierarchie():
    assert "accord_national_interprofessionnel" in DOCUMENT_TYPE_HIERARCHY


def test_parse_date_titre_standard():
    assert KaliService._parse_ani_date(_ANI_2023) == date(2023, 10, 5)


def test_parse_date_gere_le_1er():
    assert KaliService._parse_ani_date(_ANI_1ER) == date(2020, 4, 1)


def test_parse_date_avenant_prend_sa_propre_date():
    # La 1re date du titre (celle de l'avenant), pas celle de l'ANI cité.
    assert KaliService._parse_ani_date(_AVENANT_2009) == date(2009, 6, 19)


def test_parse_year_fallback_sans_jour_mois():
    titre = "Accord national interprofessionnel de 2015 sur un sujet"
    assert KaliService._parse_ani_date(titre) is None
    assert KaliService._parse_ani_year(titre) == 2015


def test_search_payload_cible_le_fond_kali_sur_le_titre():
    payload = KaliService._ani_search_payload(3)
    assert payload["fond"] == "KALI"
    rech = payload["recherche"]
    assert rech["pageNumber"] == 3
    champ = rech["champs"][0]
    assert champ["typeChamp"] == "TITLE"
    assert champ["criteres"][0]["valeur"] == "accord national interprofessionnel"


def test_format_markdown_titre_et_articles():
    articles = [
        {"num": "1", "content": "Contenu article 1", "section": "Titre I"},
        {"num": "", "content": "Préambule sans numéro", "section": ""},
    ]
    md = KaliService._format_ani_as_markdown(articles, _ANI_2023)
    assert md.startswith(f"# {_ANI_2023}")
    assert "## Titre I" in md
    assert "### Article 1" in md
    assert "Contenu article 1" in md
    # Les articles sans numéro reçoivent quand même un heading (chunker).
    assert "### Article (sans numéro 1)" in md
    assert "Préambule sans numéro" in md


def test_hierarchie_ani_niveau_et_poids():
    h = DOCUMENT_TYPE_HIERARCHY["accord_national_interprofessionnel"]
    assert h["niveau"] == 6
    assert 0.0 < h["poids"] <= 1.0
