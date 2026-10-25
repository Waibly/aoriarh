"""Immutable, lossless official CA sources, shared by bulk import and reindexing."""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date

from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.services.dila_cass_service import source_chunks
from app.services.judilibre_service import _CHAMBER_MAP
from app.services.social_ca_scope import SCOPE_POLICY_VERSION, classify_ca_scope

CA_SOURCE_PREFIX = "common/social_ca/lossless/"
SOURCE_URL_PREFIX = "https://www.courdecassation.fr/decision/"


def reference_aliases(numbers):
    return sorted({re.sub(r"[^A-Z0-9]", "", n.upper()) for n in numbers} - {""})


@dataclass(frozen=True)
class CaSource:
    raw: dict
    source_bytes: bytes
    source_id: str
    day: date
    numbers: tuple[str, ...]
    text: str
    source_sha256: str
    text_sha256: str

    @property
    def url(self):
        return SOURCE_URL_PREFIX + self.source_id

    @property
    def storage_path(self):
        return f"{CA_SOURCE_PREFIX}{self.source_id}/{self.text_sha256}.{self.source_sha256}.txt"

    def document(self):
        hierarchy = DOCUMENT_TYPE_HIERARCHY["arret_cour_appel"]
        location = self.raw["location"].removeprefix("ca_").replace("_", " ").title()
        court = f"Cour d'appel de {location}"
        chamber = _CHAMBER_MAP.get(self.raw.get("chamber", ""), self.raw.get("chamber", ""))
        return Document(
            id=uuid.uuid5(uuid.NAMESPACE_URL, self.url),
            organisation_id=None,
            source_type="arret_cour_appel",
            norme_niveau=hierarchy["niveau"],
            norme_poids=hierarchy["poids"],
            name=f"{court}, {chamber}, {self.day:%d/%m/%Y}, n° {self.numbers[0]}",
            storage_path=self.storage_path,
            file_format="txt",
            file_hash=self.text_sha256,
            file_size=len(self.text.encode()),
            indexation_status="pending",
            juridiction=court,
            chambre=chamber,
            date_decision=self.day,
            numero_pourvoi=self.numbers[0],
            solution=self.raw.get("solution") or "",
            formation=self.raw.get("formation"),
            publication=None,
            source_url=self.url,
        )

    def metadata(self):
        scope = classify_ca_scope(self.raw)
        return {
            "source_system": "judilibre",
            "source_id": self.source_id,
            "source_url": self.url,
            "source_json_sha256": self.source_sha256,
            "source_text_sha256": self.text_sha256,
            "source_metadata_version": "ca-lossless-v1",
            "court_code": self.raw["location"],
            "nac": self.raw["nac"],
            "nac_label": scope["official_label"],
            "scope_policy": SCOPE_POLICY_VERSION,
            "numero_pourvois": list(self.numbers),
            "numero_pourvoi_aliases": reference_aliases(self.numbers),
            "decision_type": self.raw["type"],
            "ecli": self.raw.get("ecli"),
            "portalis": self.raw.get("portalis"),
            "solution_alt": self.raw.get("solution_alt"),
            "source_zones": self.raw.get("zones"),
            "particular_interest": self.raw.get("particularInterest"),
        }


def parse_ca_source(raw):
    if not isinstance(raw, dict) or not re.fullmatch(r"[a-f0-9]{24}", raw.get("id", "")):
        raise ValueError("Invalid CA source ID")
    if raw.get("jurisdiction") != "ca" or raw.get("type") != "arret":
        raise ValueError("Source is not a CA arret")
    if classify_ca_scope(raw)["status"] != "admitted":
        raise ValueError("CA source outside admitted official RH NAC scope")
    day = date.fromisoformat(raw["decision_date"])
    location = raw.get("location")
    if not isinstance(location, str) or not location.startswith("ca_") or len(location) > 75:
        raise ValueError("Missing or invalid CA court identity")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty CA source text")
    numbers = raw.get("numbers") or []
    number = raw.get("number")
    if not isinstance(numbers, list) or any(
        not isinstance(n, str) or not n.strip() for n in numbers
    ):
        raise ValueError("Invalid CA case references")
    if not isinstance(number, str) or not number.strip():
        raise ValueError("Missing CA primary case reference")
    numbers = tuple(dict.fromkeys([number, *numbers]))
    if any(len(n) > 50 for n in numbers) or not all(reference_aliases([n]) for n in numbers):
        raise ValueError("CA case reference exceeds storage contract")
    for key, limit in [("chamber", 100), ("formation", 100), ("solution", 200)]:
        value = raw.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError("Invalid CA source field: " + key)
    source = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return CaSource(
        raw,
        source,
        raw["id"],
        day,
        numbers,
        text,
        hashlib.sha256(source).hexdigest(),
        hashlib.sha256(text.encode()).hexdigest(),
    )


def verified_ca_source(doc, body, sidecar):
    source = parse_ca_source(json.loads(sidecar))
    expected = source.document()
    if sidecar != source.source_bytes or body != source.text.encode():
        raise ValueError("Original CA text or source JSON differs from sealed version")
    for field in [
        "id",
        "source_type",
        "storage_path",
        "file_hash",
        "source_url",
        "date_decision",
        "juridiction",
        "chambre",
        "numero_pourvoi",
    ]:
        if getattr(doc, field) != getattr(expected, field):
            raise ValueError("CA document identity differs from source: " + field)
    if doc.organisation_id or doc.private_dossier_id or doc.private_conversation_id:
        raise ValueError("CA shared source cannot be private")
    return source


def prepared_ca_chunks(source, doc):
    from app.rag.ingestion import IngestionPipeline

    header = IngestionPipeline._build_jurisprudence_header(doc) + "\n\n"
    bodies = source_chunks(source.text)
    if "".join(bodies) != source.text:
        raise ValueError("CA source passages are incomplete")
    return [header + body for body in bodies]
