"""Service de synchronisation des BOCC (Bulletin Officiel des Conventions Collectives).

Télécharge les archives hebdomadaires depuis l'open data DILA,
inventorie les textes individuels dans une file de revue, sans ingestion.

Source : https://echanges.dila.gouv.fr/OPENDATA/BOCC/
"""

import asyncio
import hashlib
import io
import json
import logging
import re
import tarfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.bocc_metadata import extract_metadata

logger = logging.getLogger(__name__)

DILA_BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA/BOCC"
_REQUEST_TIMEOUT = 120.0

# ─── Regex patterns for parsing ───
HEADER_PATTERN_1 = re.compile(
    r"Brochure\s+n°\s*(\d+)\s*\|\s*Convention collective nationale\n"
    r"IDCC\s*:\s*(\d+)\s*\|\s*([^\n]+)\n"
    r"([\s\S]*?)\n"
    r"NOR\s*:\s*(ASET\w+)",
    re.MULTILINE,
)

HEADER_PATTERN_2 = re.compile(
    r"Convention collective nationale\n"
    r"IDCC\s*:\s*(\d+)\s*\|\s*([^\n]+)\n"
    r"([\s\S]*?)\n"
    r"NOR\s*:\s*(ASET\w+)",
    re.MULTILINE,
)

FOOTER_PATTERN = re.compile(r"^BOCC\s+\d{4}-\d+\s+TRA\s*$", re.MULTILINE)
PAGE_NUM_PATTERN = re.compile(r"^\d{1,3}\s*$", re.MULTILINE)


@dataclass
class BoccSyncResult:
    """Result of a BOCC sync run."""

    numero: str = ""
    avenants_found: int = 0
    avenants_ingested: int = 0
    avenants_stored: int = 0  # PDF entries saved in a review manifest
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    # True quand le BOCC demandé n'existe pas encore côté DILA (404 sur l'archive).
    # C'est l'état normal quand on cron quotidiennement et que DILA n'a pas
    # encore publié — il faut le distinguer d'une vraie erreur.
    not_yet_available: bool = False
    review_manifest_path: str | None = None


@dataclass
class BoccBackfillResult:
    """Result of a full BOCC backfill."""

    total_issues: int = 0
    issues_processed: int = 0
    issues_skipped: int = 0
    total_avenants: int = 0
    total_ingested: int = 0
    total_stored: int = 0
    total_errors: int = 0


class BoccService:
    """Downloads and processes BOCC archives from DILA open data."""

    async def discover_archives(self, year: int) -> dict[str, str]:
        """Resolve published archives, including the current-year directory.

        Probe both locations to survive the annual DILA move. Only 404 means
        an absent directory; transport and server errors must remain visible.
        """
        archives: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            for directory in (str(year), "FluxAnneeCourante"):
                url = f"{DILA_BASE_URL}/{directory}/"
                resp = await client.get(url)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                for code in re.findall(r'CCO(\d{8})\.complet\.taz', resp.text):
                    if int(code[:4]) == year:
                        archives.setdefault(code, f"{url}CCO{code}.complet.taz")
        return dict(sorted(archives.items()))

    async def check_available_issues(self, year: int) -> list[str]:
        """Compatibility API returning unique published issue codes."""
        return list(await self.discover_archives(year))

    @staticmethod
    def record_result(db, existing, year: int, week: int, result: BoccSyncResult):
        """Update a failed attempt in place; partial failures remain retryable."""
        from app.models.bocc_issue import BoccIssue

        issue = existing if existing is not None else BoccIssue(
            numero=f"{year}-{week:02d}", year=year, week=week,
        )
        issue.avenants_count = result.avenants_found
        issue.avenants_ingested = (issue.avenants_ingested or 0) + result.avenants_ingested
        if result.errors:
            issue.status = "error"
        elif result.review_manifest_path:
            issue.status = "review_pending"
        else:
            issue.status = "processed"
        issue.error_message = "; ".join(result.error_messages[:3]) or None
        issue.processed_at = datetime.now(UTC)
        db.add(issue)
        return issue

    async def backfill_all(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        year_start: int = 2023,
        year_end: int | None = None,
    ) -> BoccBackfillResult:
        """Download and process ALL BOCC archives from year_start to year_end."""
        import asyncio
        from datetime import date

        from app.models.bocc_issue import BoccIssue

        if year_end is None:
            year_end = date.today().year

        result = BoccBackfillResult()

        for year in range(year_start, year_end + 1):
            # List available issues for this year
            try:
                archives = await self.discover_archives(year)
                issue_codes = list(archives)
            except Exception as exc:
                result.total_errors += 1
                logger.warning("BOCC backfill: failed to list %d: %s", year, exc)
                continue

            for code in issue_codes:
                # code is like "20250012" → year=2025, week=12
                week = int(code[4:])
                numero = f"{year}-{week:02d}"
                result.total_issues += 1

                # Skip if already processed
                existing = await db.execute(
                    select(BoccIssue).where(BoccIssue.numero == numero)
                )
                previous = existing.scalar_one_or_none()
                if previous is not None and previous.status in {"processed", "review_pending"}:
                    result.issues_skipped += 1
                    continue

                logger.info("BOCC backfill: processing %s (%d/%d for %d)",
                            numero, result.issues_processed + 1, len(issue_codes), year)

                try:
                    sync_result = await self.process_issue(
                        db, year, week, user_id, archive_url=archives[code],
                    )
                    if sync_result.not_yet_available:
                        result.issues_skipped += 1
                        continue

                    if previous is not None:
                        await db.refresh(previous)
                    self.record_result(db, previous, year, week, sync_result)
                    await db.commit()

                    result.issues_processed += 1
                    result.total_avenants += sync_result.avenants_found
                    result.total_ingested += sync_result.avenants_ingested
                    result.total_stored += sync_result.avenants_stored
                    result.total_errors += sync_result.errors

                except Exception as exc:
                    result.total_errors += 1
                    logger.warning("BOCC backfill: failed %s: %s", numero, exc)
                    await db.rollback()

                # Throttle to avoid hammering DILA
                await asyncio.sleep(1.0)

            logger.info("BOCC backfill: year %d done — %d processed, %d skipped",
                        year, result.issues_processed, result.issues_skipped)

        logger.info(
            "BOCC backfill complete — %d issues (%d processed, %d skipped), "
            "%d avenants found, %d ingested, %d stored, %d errors",
            result.total_issues, result.issues_processed, result.issues_skipped,
            result.total_avenants, result.total_ingested, result.total_stored,
            result.total_errors,
        )
        return result

    async def ingest_bocc_for_idcc(self, db: AsyncSession, idcc: str) -> int:
        """Legacy installation hook: BOCC admission requires a reviewed lot.

        Installing a branch must not index old reserves automatically either.
        Existing reserves remain intact until an explicit admission operation.
        """
        logger.info("BOCC %s: automatic admission disabled; documentary review required", idcc)
        return 0

    @staticmethod
    def review_path(year: int, week: int) -> str:
        if not 1900 <= year <= 2100 or not 1 <= week <= 99:
            raise ValueError("Invalid BOCC issue")
        return f"common/bocc_review/{year}-{week:02d}/manifest.json"

    async def process_issue(
        self,
        db: AsyncSession,
        year: int,
        week: int,
        user_id: uuid.UUID,
        *,
        archive_url: str | None = None,
    ) -> BoccSyncResult:
        """Inventory a BOCC issue for review; never enqueue or create RAG documents."""
        numero = f"{year}-{week:02d}"
        archive_name = f"CCO{year}{week:04d}"
        result = BoccSyncResult(numero=numero)

        try:
            # 1. Download archive
            if archive_url is None:
                archives = await self.discover_archives(year)
                archive_url = archives.get(f"{year}{week:04d}")
            if archive_url is None:
                result.not_yet_available = True
                return result
            # Only a canonical DILA archive URL may be downloaded.
            allowed = {
                f"{DILA_BASE_URL}/{directory}/{archive_name}.complet.taz"
                for directory in (str(year), "FluxAnneeCourante")
            }
            if archive_url not in allowed:
                raise ValueError("Invalid BOCC archive URL")
            url = archive_url
            logger.info("BOCC: downloading %s", url)

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    # DILA n'a pas encore publié ce BOCC : état normal, pas une erreur.
                    # Le caller logge cela en 'success / 0 items' (cf. run_bocc_sync).
                    result.not_yet_available = True
                    return result
                resp.raise_for_status()
                archive_bytes = resp.content

            # 2. Extract individual PDFs from .taz
            pdfs = self._extract_individual_pdfs(archive_bytes)
            logger.info("BOCC %s: %d PDFs individuels extraits", numero, len(pdfs))
            if not pdfs:
                raise ValueError("Archive BOCC sans PDF individuel exploitable")

            # Inventory every PDF, even without an IDCC or recognizable header.
            # This creates no Document, queue job or searchable vector.
            import pymupdf

            from app.services.storage_service import StorageService

            entries = []
            for pdf_name, pdf_bytes in pdfs:
                entry = {
                    "pdf": pdf_name,
                    "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                    "admission": "review_required",
                }
                try:
                    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
                        raw = "\n".join(page.get_text() for page in pdf)
                        entry["pages"] = len(pdf)
                    entry.update(extract_metadata(raw))
                    if not entry["nor"] or not entry["title"]:
                        entry["metadata_status"] = "unresolved"
                    else:
                        entry["metadata_status"] = "identified"
                except Exception as exc:
                    entry["metadata_status"] = "error"
                    entry["error"] = str(exc)[:300]
                    result.errors += 1
                    result.error_messages.append(f"{pdf_name}: {str(exc)[:100]}")
                entries.append(entry)
            result.avenants_found = len(entries)
            manifest = {
                "schema_version": 1, "numero": numero, "source_url": url,
                "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
                "captured_at": datetime.now(UTC).isoformat(),
                "documents": entries, "indexation_requested": False,
            }
            path = self.review_path(year, week)
            storage = StorageService()
            await asyncio.to_thread(
                storage.put_file_bytes, path,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                content_type="application/json",
            )
            result.review_manifest_path = path
            result.avenants_stored = len(entries)

        except Exception as exc:
            result.errors += 1
            result.error_messages.append(str(exc)[:500])
            logger.exception("BOCC %s: sync failed", numero)

        return result

    def _extract_individual_pdfs(self, archive_bytes: bytes) -> list[tuple[str, bytes]]:
        """Read tar, gzip tar or historical Unix-compress archives.

        HTTP Content-Encoding may already have been decoded by httpx. Detect
        the actual bytes instead of inferring compression from the .taz suffix.
        No member is extracted to the filesystem.
        """
        import subprocess

        try:
            if archive_bytes.startswith(b"\x1f\x9d"):
                proc = subprocess.run(
                    ["gzip", "-dc"], input=archive_bytes,
                    capture_output=True, timeout=120, check=True,
                )
                archive_bytes = proc.stdout
            pdfs = []
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
                for member in tar:
                    if (member.isfile() and member.name.endswith(".pdf")
                            and "_0000_" in member.name):
                        file = tar.extractfile(member)
                        if file is not None:
                            pdfs.append((member.name, file.read()))
            return pdfs
        except (tarfile.TarError, subprocess.SubprocessError, OSError) as exc:
            logger.warning("BOCC: failed to extract archive: %s", exc)
            return []

    def _parse_avenant_pdf(self, pdf_bytes: bytes) -> dict | None:
        """Parse a single avenant PDF and extract metadata + content.

        Use pymupdf4llm to preserve tables in markdown format — BOCC
        avenants frequently contain salary grids and minima tables that
        were previously aplattis to unreadable text by ``get_text("text")``.
        We still keep a plain-text fallback when the markdown extractor
        fails (corrupted PDF, etc.).
        """
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            import pymupdf4llm
            full_text = pymupdf4llm.to_markdown(doc)
        except Exception:
            pages_text = [page.get_text("text") for page in doc]
            full_text = "\n".join(pages_text)
        doc.close()

        # Try both header patterns
        match = HEADER_PATTERN_1.search(full_text)
        if match:
            meta = {
                "brochure": match.group(1),
                "idcc": match.group(2).zfill(4),
                "ccn_name": match.group(3).strip(),
                "titre_raw": match.group(4).strip(),
                "nor": match.group(5),
            }
        else:
            match = HEADER_PATTERN_2.search(full_text)
            if not match:
                return None
            meta = {
                "brochure": "",
                "idcc": match.group(1).zfill(4),
                "ccn_name": match.group(2).strip(),
                "titre_raw": match.group(3).strip(),
                "nor": match.group(4),
            }

        # Extract title
        titre_match = re.search(
            r"((?:Accord|Avenant|Protocole|Annexe)[^\n]*(?:\n[^\n]*?)?)"
            r"(?=\s*NOR\s*:|$)",
            match.group(0),
            re.IGNORECASE,
        )
        titre = re.sub(r"\s+", " ", titre_match.group(1)).strip() if titre_match else meta["titre_raw"]

        # Clean title
        titre = re.sub(r"^\([^)]+\)\s*", "", titre)
        titre = re.sub(r"^[A-ZÉÈÊËÀÂÔÎÏÙÛÜÇ\s,.'()-]+(?=Accord|Avenant|Protocole|Annexe)", "", titre).strip()
        if titre and titre[0].islower():
            titre = titre[0].upper() + titre[1:]

        # Extract content (everything after the NOR line)
        content_start = match.end()
        content = full_text[content_start:]
        content = self._clean_content(content)

        return {
            "idcc": meta["idcc"],
            "brochure": meta["brochure"],
            "ccn_name": meta["ccn_name"],
            "titre": titre,
            "nor": meta["nor"],
            "content": content,
        }

    @staticmethod
    def _clean_content(text: str) -> str:
        """Clean avenant content."""
        text = FOOTER_PATTERN.sub("", text)
        text = PAGE_NUM_PATTERN.sub("", text)
        text = re.sub(r"^IDCC\s*:\s*\d+\s*$", "", text, count=1, flags=re.MULTILINE)
        text = re.sub(r"^MINISTÈRE\s+DU\s+TRAVAIL[^\n]*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^MINISTÈRE\s+DE\s+L.AGRICULTURE[^\n]*$", "", text, flags=re.MULTILINE)
        # Fix césure
        text = re.sub(r"\xad\s*\n\s*", "", text)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        # Format articles as markdown
        text = re.sub(r"^(Article\s+\d+[\w]*(?:\s*\|[^\n]*)?)", r"### \1", text, flags=re.MULTILINE)
        text = re.sub(r"^(Préambule)\s*$", r"### Préambule", text, flags=re.MULTILINE)
        # Normalize
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _format_as_markdown(avenant: dict, bocc_numero: str) -> str:
        """Format avenant as clean markdown document."""
        lines = [
            f"# {avenant['titre']}",
            "",
            f"**Convention collective** : {avenant['ccn_name']} (IDCC {avenant['idcc']})",
        ]
        if avenant["brochure"]:
            lines.append(f"**Brochure** : n° {avenant['brochure']}")
        lines.extend([
            f"**NOR** : {avenant['nor']}",
            f"**Source** : BOCC n° {bocc_numero}",
            "",
            "---",
            "",
            avenant["content"],
        ])
        return "\n".join(lines)
