"""Bounded maintenance of explicitly admitted sources, never a site-wide crawler.

Only practical guides and an explicit CPC article selection may be refreshed.
Other legal publications are archived for review. No generated text is processed.
"""

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from botocore.exceptions import ClientError
from lxml import etree, html

from app.models.document import Document
from app.services.html_to_markdown import html_to_markdown
from app.services.storage_service import StorageService

MAX_BYTES = 8_000_000
MAX_RUN_TOKENS = 300_000
MAX_DOCUMENT_TOKENS = 100_000
MAX_UPDATES = 6
PREFIX = "common/curated_maintenance/"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def extract_body(spec, raw):
    """Technical source-format contract, not a semantic/LLM quality check."""
    if spec["format"] == "pdf":
        import pymupdf

        if not raw.startswith(b"%PDF-"):
            raise ValueError("Source is not a PDF")
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            body = "\n\n".join(page.get_text() for page in pdf)
    else:
        tree = html.fromstring(raw.decode("utf-8-sig"))
        nodes = tree.xpath(spec["xpath"])
        if len(nodes) != 1:
            raise ValueError("Source content element absent or ambiguous")
        node = nodes[0]
        for child in node.xpath(
            ".//script | .//style | .//nav | .//form" + spec.get("remove_xpath", "")
        ):
            child.drop_tree()
        # Preserve citations and links in the source body, without following them.
        for link in node.xpath(".//a[@href]"):
            href = urljoin(spec["url"], link.get("href"))
            if urlsplit(href).scheme in {"https", "http"}:
                link.tail = " (" + href + ")" + (link.tail or "")
        body = html_to_markdown(etree.tostring(node, encoding="unicode", method="html"))
    if not body.strip():
        raise ValueError("Empty source text")
    return body


async def fetch_browser_source(spec):
    """Direct HTTPS with browser-compatible transport, for approved public sources."""
    from curl_cffi.requests import AsyncSession

    url = spec.get("fetch_url", spec["url"])
    hosts = set(spec["allowed_hosts"])
    async with AsyncSession(impersonate="chrome", verify=True, timeout=30) as session:
        for _ in range(5):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in hosts
                or parsed.port not in (None, 443)
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Unapproved source redirect")
            async with session.stream("GET", url, allow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_content():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("Source exceeds download budget")
                if not raw:
                    raise ValueError("Empty source response")
                return bytes(raw), url
    raise ValueError("Too many source redirects")


async def fetch_source(client, spec):
    if spec.get("transport") == "browser_http":
        return await fetch_browser_source(spec)
    url = spec.get("fetch_url", spec["url"])
    hosts = set(spec["allowed_hosts"])
    for _ in range(5):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Unapproved source redirect")
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Source exceeds download budget")
            if not raw:
                raise ValueError("Empty source response")
            return bytes(raw), url
    raise ValueError("Too many source redirects")


async def fetch_cpc(spec, today):
    from app.services.legi_service import LegiService

    async with httpx.AsyncClient(timeout=120) as client:
        data = await LegiService()._api_post(
            client,
            "/consult/legiPart",
            {
                "textId": "LEGITEXT000006070716",
                "date": today.isoformat(),
            },
        )
    if not data or not data.get("sections"):
        raise ValueError("Incomplete CPC response")
    selected = {}

    def walk(value, path):
        if isinstance(value, dict):
            path = path + ([value["title"]] if value.get("title") else [])
            if value.get("num") in spec["articles"] and value.get("etat") == "VIGUEUR":
                number = value["num"]
                if number in selected:
                    raise ValueError("Ambiguous current CPC article")
                selected[number] = (value, value.get("pathTitle") or path)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    walk(child, path)
        elif isinstance(value, list):
            for child in value:
                walk(child, path)

    walk(data, [])
    if set(selected) != set(spec["articles"]):
        raise ValueError(
            "Selected CPC articles missing: "
            + ", ".join(sorted(set(spec["articles"]) - set(selected)))
        )
    parts = [
        "Sélection de 45 articles du Code de procédure civile. Les contextes de juridiction et notes officielles sont conservés. Pour la procédure prud’homale, voir le renvoi de l’article 879 au Code du travail."
    ]
    for number in spec["articles"]:
        article, path = selected[number]
        if not article.get("content"):
            raise ValueError("Empty CPC article")
        parts.append(
            "## Article "
            + number
            + "\n\n"
            + " > ".join(path)
            + "\n\nSource : https://www.legifrance.gouv.fr/codes/article_lc/"
            + article["id"]
            + "/\n\n"
            + html_to_markdown(article["content"])
        )
        if article.get("nota"):
            parts.append("Note d’application officielle :\n\n" + html_to_markdown(article["nota"]))
    return "\n\n".join(parts), json.dumps(data, ensure_ascii=False).encode()


class CuratedSourceService:
    def __init__(self, storage=None):
        self.storage = storage or StorageService()

    def read_json(self, key):
        try:
            return json.loads(self.storage.get_file_bytes_bounded(key, MAX_BYTES))
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in {"NoSuchKey", "404"}:
                return None
            raise

    def save_json(self, key, value):
        raw = json.dumps(value, ensure_ascii=False, default=str).encode()
        self.storage.put_file_bytes(key, raw, "application/json")
        if self.storage.get_file_bytes_bounded(key, len(raw) + 1) != raw:
            raise ValueError("Source archive verification failed")

    async def sync(self, db, *, apply=True, sources=None):
        from app.services.curated_source_registry import SOURCES

        sources = SOURCES if sources is None else sources
        result = {
            "checked": 0,
            "updated": 0,
            "unchanged": 0,
            "pending": 0,
            "errors": 0,
            "tokens_reserved": 0,
            "sources": [],
        }
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={
                "User-Agent": "AORIA-documentary-review/1.0",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
        ) as client:
            for spec in sources:
                item = {
                    "key": spec["key"],
                    "name": spec.get("name", spec["key"]),
                    "transport": spec.get("transport", "httpx"),
                    "url": spec["url"],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    if spec["format"] == "cpc":
                        body, raw = await fetch_cpc(spec, date.today())
                        final_url = spec["url"]
                    else:
                        raw, final_url = await fetch_source(client, spec)
                        body = extract_body(spec, raw)
                    sha = digest(body.encode())
                    evidence = {
                        **item,
                        "final_url": final_url,
                        "body_sha256": sha,
                        "raw_sha256": digest(raw),
                        "body": body,
                    }
                    raw_key = PREFIX + "sources/" + spec["key"] + "/" + digest(raw)
                    self.storage.put_file_bytes(raw_key, raw)
                    evidence["raw_path"] = raw_key
                    self.save_json(
                        PREFIX + "evidence/" + spec["key"] + "/" + sha + ".json", evidence
                    )
                    result["checked"] += 1
                    doc = (
                        await db.get(Document, uuid.UUID(spec["document_id"]))
                        if spec.get("document_id")
                        else None
                    )
                    if doc:
                        if (
                            doc.organisation_id
                            or doc.private_dossier_id
                            or doc.private_conversation_id
                            or doc.retired_at
                            or doc.source_type != spec["source_type"]
                            or doc.source_url != spec["url"]
                        ):
                            raise ValueError("Source document access or identity mismatch")
                    state = self.read_json(PREFIX + "state/" + spec["key"] + ".json")
                    expected = state or {
                        "body_sha256": spec.get("baseline_body_sha256"),
                        "document_sha256": spec.get("baseline_document_sha256"),
                        "raw_sha256": spec.get("baseline_raw_sha256"),
                    }
                    if (
                        doc
                        and doc.file_hash == expected.get("document_sha256")
                        and (
                            sha == expected.get("body_sha256")
                            or digest(raw) == expected.get("raw_sha256")
                        )
                    ):
                        item["status"] = "unchanged"
                        result["unchanged"] += 1
                    elif (
                        doc
                        and spec["policy"] == "refresh"
                        and doc.indexation_status == "indexed"
                        and doc.file_hash
                        == digest(
                            (
                                "# "
                                + spec["name"]
                                + "\n\nSource officielle : "
                                + spec["url"]
                                + "\n\n"
                                + body
                            ).encode()
                        )
                    ):
                        self.save_json(
                            PREFIX + "state/" + spec["key"] + ".json",
                            {
                                "body_sha256": sha,
                                "raw_sha256": digest(raw),
                                "document_sha256": doc.file_hash,
                                "updated_at": item["checked_at"],
                            },
                        )
                        item["status"] = "unchanged"
                        result["unchanged"] += 1
                    elif spec["policy"] != "refresh" or not apply or not doc:
                        item["status"] = "review_pending"
                        result["pending"] += 1
                    else:
                        if doc.file_hash != expected.get("document_sha256"):
                            raise ValueError("Document changed outside source maintenance")
                        if doc.indexation_status != "indexed":
                            raise ValueError("Document is not ready for replacement")
                        text = (
                            "# "
                            + spec["name"]
                            + "\n\nSource officielle : "
                            + spec["url"]
                            + "\n\n"
                            + body
                        )
                        from app.rag.ingestion import IngestionPipeline, ARTICLE_AWARE_SOURCE_TYPES
                        from app.rag.text_cleaner import clean_text
                        import tiktoken

                        pipeline = IngestionPipeline()
                        cleaned = clean_text(text)
                        chunks = (
                            [c.text for c in pipeline.article_chunker.chunk_with_meta(cleaned)]
                            if doc.source_type in ARTICLE_AWARE_SOURCE_TYPES
                            else pipeline.chunker.chunk(cleaned)
                        )
                        enc = tiktoken.get_encoding("cl100k_base")
                        tokens = sum(len(enc.encode(c, disallowed_special=())) for c in chunks)
                        if (
                            tokens > MAX_DOCUMENT_TOKENS
                            or result["tokens_reserved"] + tokens > MAX_RUN_TOKENS
                            or result["updated"] >= MAX_UPDATES
                        ):
                            item["status"] = "budget_pending"
                            result["pending"] += 1
                        else:
                            result["tokens_reserved"] += tokens
                            await self.replace(db, doc, text, pipeline, tokens, name=spec["name"])
                            self.save_json(
                                PREFIX + "state/" + spec["key"] + ".json",
                                {
                                    "body_sha256": sha,
                                    "raw_sha256": digest(raw),
                                    "document_sha256": doc.file_hash,
                                    "updated_at": item["checked_at"],
                                },
                            )
                            item["status"] = "updated"
                            result["updated"] += 1
                    item["body_sha256"] = sha
                except Exception as exc:
                    await db.rollback()
                    item.update(status="error", error=type(exc).__name__ + ": " + str(exc)[:300])
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
                        item.update(
                            status="access_blocked", http_status=403,
                            error=("Accès refusé par la source (HTTP 403) ; mise à jour bloquée, "
                                   "document existant conservé."),
                            technical_error=type(exc).__name__ + ": " + str(exc)[:1000],
                        )
                    result["errors"] += 1
                result["sources"].append(item)
                self.save_json(PREFIX + "latest.json", result)
        return result

    async def replace(self, db, doc, text, pipeline, tokens, *, name):
        """Backup and guarded replacement. Restore prior vectors on technical failure."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct
        from app.rag.qdrant_store import COLLECTION_NAME

        old = {column.name: getattr(doc, column.name) for column in Document.__table__.columns}
        points, offset = [], None
        filt = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=str(doc.id)))])
        while True:
            batch, offset = pipeline.qdrant.scroll(
                COLLECTION_NAME,
                scroll_filter=filt,
                offset=offset,
                limit=100,
                with_payload=True,
                with_vectors=True,
            )
            points.extend(batch)
            if offset is None:
                break
        if len(points) != doc.chunk_count or any(
            p.payload.get("organisation_id") != "common" or p.payload.get("private") for p in points
        ):
            raise ValueError("Existing index does not match source document")
        backup_key = PREFIX + "backups/" + str(doc.id) + "/" + str(uuid.uuid4()) + ".json"
        self.save_json(
            backup_key, {"document": old, "points": [p.model_dump(mode="json") for p in points]}
        )
        raw = text.encode()
        sha = digest(raw)
        key = PREFIX + "published/" + str(doc.id) + "/" + sha + ".txt"
        self.storage.put_file_bytes(key, raw, "text/plain; charset=utf-8")
        if self.storage.get_file_bytes_bounded(key, len(raw) + 1) != raw:
            raise ValueError("Published source archive verification failed")
        # Commit only the explicitly bound public document; no discovered document is created.
        await db.refresh(doc)
        if doc.file_hash != old["file_hash"] or doc.storage_path != old["storage_path"]:
            raise ValueError("Concurrent source replacement")
        doc.storage_path, doc.file_hash, doc.file_size = key, sha, len(raw)
        doc.file_format, doc.indexation_status = "txt", "pending"
        doc.name = name
        await db.commit()

        async def plain_extract(document, file_bytes, session):
            return file_bytes.decode("utf-8")

        pipeline._extract_document_text = plain_extract
        try:
            await pipeline.ingest(doc.id, db, expected_source=key, max_embedding_tokens=tokens)
            await db.refresh(doc)
            if doc.storage_path != key:
                raise ValueError("Concurrent source replacement during indexing")
            if doc.indexation_status != "indexed":
                raise ValueError("Source indexing failed: " + str(doc.indexation_error))
        except Exception:
            await db.rollback()
            await db.refresh(doc)
            if doc.storage_path == key:
                for start in range(0, len(points), 100):
                    pipeline.qdrant.upsert(
                        COLLECTION_NAME,
                        points=[
                            PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                            for p in points[start : start + 100]
                        ],
                        wait=True,
                    )
                pipeline._cleanup_old_chunks(str(doc.id), {str(p.id) for p in points}, strict=True)
                for field, value in old.items():
                    setattr(doc, field, value)
                await db.commit()
            raise
