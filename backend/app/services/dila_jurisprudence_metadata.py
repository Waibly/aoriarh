"""Source-backed retrieval metadata. Never creates topics or assesses current law."""

import hashlib

from lxml import etree

from app.services.dila_cass_service import (
    number_aliases,
    parse_social_xml,
    reconcile_source_references,
)
from app.services.jurisprudence_references import social_case_references


def source_metadata(raw: bytes, *, reference_reconciliation: dict | None = None) -> dict:
    decision = parse_social_xml(raw)
    declared_numbers = list(decision.numbers)
    decision = reconcile_source_references(decision, reference_reconciliation)
    root = etree.fromstring(
        raw, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    )
    primary = root.find("TEXTE/BLOC_TEXTUEL/CONTENU")
    # Fields below are documentary facts, not inferred legal significance.
    result = {
        "source_identifier": decision.source_id,
        "source_url": "https://www.legifrance.gouv.fr/juri/id/" + decision.source_id,
        "source_xml_sha256": decision.xml_sha256,
        "source_text_sha256": decision.text_sha256,
        "numero_pourvois": list(decision.numbers),
        "numero_pourvoi_aliases": sorted({
            alias for number in decision.numbers for alias in number_aliases(number)
        }),
        "documentary_topics": list(decision.topics),
        "social_case_citations": social_case_references(decision.text),
        "primary_body_text_sha256": hashlib.sha256(
            "".join(primary.itertext()).encode()
        ).hexdigest(),
    }
    if reference_reconciliation is not None:
        result["source_declared_case_numbers"] = declared_numbers
        result["case_reference_reconciliation"] = reference_reconciliation
    for key, path in {
        "appealed_court": "META/META_SPEC/META_JURI_JUDI/FORM_DEC_ATT",
        "appealed_decision_date": "META/META_SPEC/META_JURI_JUDI/DATE_DEC_ATT",
    }.items():
        value = root.findtext(path)
        if value and value.strip():
            result[key] = value
    return result
