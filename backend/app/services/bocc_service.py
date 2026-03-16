"""Service de synchronisation des BOCC (Bulletin Officiel des Conventions Collectives).

Télécharge les archives hebdomadaires depuis l'open data DILA,
extrait les avenants individuels et les ingère dans le référentiel CCN.

Source : https://echanges.dila.gouv.fr/OPENDATA/BOCC/
"""

import hashlib
import io
import logging
import re
import tarfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ccn import OrganisationConvention
from app.models.document import Document
from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.rag.tasks import enqueue_ingestion

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
    avenants_stored: int = 0  # stored but not ingested (CCN not installed)
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


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

    async def check_available_issues(self, year: int) -> list[str]:
        """List available BOCC issue numbers for a given year."""
        url = f"{DILA_BASE_URL}/{year}/"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            # Parse HTML directory listing for .taz files
            matches = re.findall(r"CCO(\d{8})\.complet\.taz", resp.text)
            return sorted(matches)

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
                issue_codes = await self.check_available_issues(year)
            except Exception as exc:
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
                if existing.scalar_one_or_none():
                    result.issues_skipped += 1
                    continue

                logger.info("BOCC backfill: processing %s (%d/%d for %d)",
                            numero, result.issues_processed + 1, len(issue_codes), year)

                try:
                    sync_result = await self.process_issue(db, year, week, user_id)

                    # Record in bocc_issues
                    issue = BoccIssue(
                        numero=numero,
                        year=year,
                        week=week,
                        avenants_count=sync_result.avenants_found,
                        avenants_ingested=sync_result.avenants_ingested,
                        status="error" if sync_result.errors > 0 and sync_result.avenants_found == 0 else "processed",
                        error_message="; ".join(sync_result.error_messages[:3]) if sync_result.error_messages else None,
                        processed_at=datetime.now(UTC),
                    )
                    db.add(issue)
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
        """Ingest all pending BOCC documents for a given IDCC.

        Called after a CCN is installed to ingest stored BOCC avenants.
        Returns the number of documents enqueued for ingestion.
        """
        # Find all BOCC docs for this IDCC that are stored but not yet indexed
        bocc_docs = await db.execute(
            select(Document).where(
                Document.organisation_id.is_(None),
                Document.storage_path.ilike(f"common/ccn/{idcc}/bocc_%"),
                Document.indexation_status == "pending",
            )
        )
        docs = bocc_docs.scalars().all()

        count = 0
        for doc in docs:
            await enqueue_ingestion(str(doc.id))
            count += 1

        if count:
            logger.info("BOCC: enqueued %d pending docs for IDCC %s", count, idcc)
        return count

    async def process_issue(
        self,
        db: AsyncSession,
        year: int,
        week: int,
        user_id: uuid.UUID,
    ) -> BoccSyncResult:
        """Download and process a single BOCC issue."""
        numero = f"{year}-{week:02d}"
        archive_name = f"CCO{year}{week:04d}"
        result = BoccSyncResult(numero=numero)

        try:
            # 1. Download archive
            url = f"{DILA_BASE_URL}/{year}/{archive_name}.complet.taz"
            logger.info("BOCC: downloading %s", url)

            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    result.errors = 1
                    result.error_messages.append(f"Archive {archive_name} introuvable")
                    return result
                resp.raise_for_status()
                archive_bytes = resp.content

            # 2. Extract individual PDFs from .taz
            pdfs = self._extract_individual_pdfs(archive_bytes)
            logger.info("BOCC %s: %d PDFs individuels extraits", numero, len(pdfs))

            # 3. Parse each PDF
            from app.services.storage_service import StorageService
            storage = StorageService()

            for pdf_name, pdf_bytes in pdfs:
                try:
                    avenant = self._parse_avenant_pdf(pdf_bytes)
                    if avenant is None:
                        continue

                    result.avenants_found += 1

                    # Store in MinIO
                    md_content = self._format_as_markdown(avenant, numero)
                    md_bytes = md_content.encode("utf-8")
                    file_hash = hashlib.sha256(md_bytes).hexdigest()

                    storage_path = f"common/ccn/{avenant['idcc']}/bocc_{numero}_{avenant['nor']}.md"

                    # Check if already exists (dedup by NOR)
                    existing = await db.execute(
                        select(Document).where(
                            Document.organisation_id.is_(None),
                            Document.name.ilike(f"%{avenant['nor']}%"),
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none():
                        continue  # Already processed

                    storage.put_file_bytes(storage_path, md_bytes, content_type="text/plain")

                    # Create document in DB
                    hierarchy = DOCUMENT_TYPE_HIERARCHY["convention_collective_nationale"]
                    doc = Document(
                        organisation_id=None,  # Common document
                        name=f"{avenant['titre'][:200]} (IDCC {avenant['idcc']}) — BOCC {numero}",
                        source_type="convention_collective_nationale",
                        norme_niveau=hierarchy["niveau"],
                        norme_poids=hierarchy["poids"],
                        storage_path=storage_path,
                        indexation_status="pending",
                        uploaded_by=user_id,
                        file_size=len(md_bytes),
                        file_format="md",
                        file_hash=file_hash,
                    )
                    db.add(doc)
                    await db.commit()
                    await db.refresh(doc)

                    # Check if this CCN is installed — if yes, ingest now
                    installed = await db.execute(
                        select(OrganisationConvention).where(
                            OrganisationConvention.idcc == avenant["idcc"],
                        ).limit(1)
                    )
                    if installed.scalar_one_or_none():
                        await enqueue_ingestion(str(doc.id))
                        result.avenants_ingested += 1
                    else:
                        result.avenants_stored += 1

                except Exception as exc:
                    result.errors += 1
                    result.error_messages.append(f"{pdf_name}: {str(exc)[:100]}")
                    logger.warning("BOCC %s: failed to parse %s: %s", numero, pdf_name, exc)

        except Exception as exc:
            result.errors += 1
            result.error_messages.append(str(exc)[:500])
            logger.exception("BOCC %s: sync failed", numero)

        return result

    def _extract_individual_pdfs(self, archive_bytes: bytes) -> list[tuple[str, bytes]]:
        """Extract individual avenant PDFs from a .taz archive.

        .taz files are .tar.Z (Unix compress format), not .tar.gz.
        We decompress with subprocess (uncompress/gzip) then open as plain tar.
        """
        import subprocess
        import tempfile

        pdfs = []
        try:
            # Write to temp file, decompress with gzip (handles .Z format)
            with tempfile.NamedTemporaryFile(suffix=".taz", delete=False) as tmp:
                tmp.write(archive_bytes)
                tmp_path = tmp.name

            # gzip -d can decompress .Z files; output to stdout as tar
            proc = subprocess.run(
                ["gzip", "-dc", tmp_path],
                capture_output=True,
                timeout=120,
            )
            import os
            os.unlink(tmp_path)

            if proc.returncode != 0:
                logger.warning("BOCC: gzip decompress failed: %s", proc.stderr[:200])
                return pdfs

            tar_bytes = proc.stdout
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
                for member in tar.getmembers():
                    name = member.name
                    # Individual avenants: boc_XXXX_0000_NNNN.pdf (not the complete PDF _0001_p000)
                    if name.endswith(".pdf") and "_0000_" in name:
                        f = tar.extractfile(member)
                        if f:
                            pdfs.append((name, f.read()))
        except (tarfile.TarError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("BOCC: failed to extract archive: %s", exc)
        return pdfs

    def _parse_avenant_pdf(self, pdf_bytes: bytes) -> dict | None:
        """Parse a single avenant PDF and extract metadata + content."""
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        pages_text = [page.get_text("text") for page in doc]
        doc.close()

        full_text = "\n".join(pages_text)

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
