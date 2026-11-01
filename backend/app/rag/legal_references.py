"""Explicit documentary links: outgoing across sections, inverse within root unit."""

import re


def norm(value):
    return re.sub(r"[.\s]", "", value).upper().replace("‑", "-").replace("–", "-")


def unit(value):
    parts = [part.strip() for part in (value or "").split(" > ")]
    for prefix in ("Sous-section", "Section", "Chapitre"):
        indices = [i for i, part in enumerate(parts) if part.startswith(prefix)]
        if indices:
            return tuple(parts[: indices[-1] + 1])
    return tuple(parts[:-1])


def refs(text):
    return {
        norm("".join(m.groups()))
        for m in re.finditer(r"\b([LRDA])\.?\s*(\d{1,4})([-‑–]\d+(?:[-‑–]\d+)*)\b", text, re.I)
    }


def explicit_reference_scopes(text, code_labels):
    """Scope adjacent named Codes/lists; leave unknown named Codes unresolved."""
    mentions = list(re.finditer(r"\b([LRDA])\.?\s*(\d{1,4})([-‑–]\d+(?:[-‑–]\d+)*)\b", text, re.I))
    scopes = {}
    known_starts = set()

    def assign(code_start, types):
        prior = [i for i, m in enumerate(mentions) if m.end() <= code_start]
        if not prior:
            return
        i = prior[-1]
        m = mentions[i]
        if not re.fullmatch(
            r"\s*(?:du(?:\s+même)?|de la|de l['’]|des)\s*", text[m.end() : code_start], re.I
        ):
            return
        while True:
            reference = norm("".join(mentions[i].groups()))
            scopes[reference] = sorted(set(scopes.get(reference, [])) | set(types))
            if not i or not re.fullmatch(
                r"[\s,]*(?:(?:et|ou|à)[\s,]*)?",
                text[mentions[i - 1].end() : mentions[i].start()],
                re.I,
            ):
                break
            i -= 1

    for label_pattern, types in code_labels.items():
        for code in re.finditer(label_pattern, text, re.I):
            known_starts.add(code.start())
            assign(code.start(), types)
    for code in re.finditer(r"\bcode\b", text, re.I):
        if code.start() not in known_starts:
            assign(code.start(), ["__unresolved_named_code__"])
    return scopes


def build_graph(root, points, rounds=2, scope_resolver=None):
    nodes = []
    for point in points:
        d = point.get("payload") or {}
        if any(
            d.get(k) != root.get(k)
            for k in (
                "document_id",
                "organisation_id",
                "source_type",
                "instrument_id",
                "effective_from",
                "effective_to",
                "instrument_status",
            )
        ):
            continue
        own = {norm(a) for a in d.get("article_nums") or []}
        if not own:
            continue
        all_refs = refs(d.get("text", "")) - own
        scopes = scope_resolver(d.get("text", "")) if scope_resolver else {}
        external = {
            ref for ref in all_refs if scopes.get(ref) and d.get("source_type") not in scopes[ref]
        }
        nodes.append(
            {
                "point_id": str(point["id"]),
                "own": sorted(own),
                "references": sorted(all_refs - external),
                "external_references": sorted(external),
                "payload": d,
            }
        )
    # Never merge competing versions of one article within an instrument.
    versions = {}
    for node in nodes:
        payload = node["payload"]
        version = tuple(
            payload.get(k)
            for k in (
                "article_id",
                "article_effective_from",
                "article_effective_to",
                "article_status",
            )
        )
        for article in node["own"]:
            versions.setdefault(article, set()).add(version)
    ambiguous = {a for a, values in versions.items() if len(values) > 1}
    nodes = [n for n in nodes if not set(n["own"]) & ambiguous]
    active = {norm(a) for a in root["article_nums"]}
    selected = set()
    steps = []
    for number in range(1, rounds + 1):
        outgoing = {ref for n in nodes if set(n["own"]) & active for ref in n["references"]}
        direct = [n for n in nodes if set(n["own"]) & (active | outgoing)]
        inverse = [
            n
            for n in nodes
            if unit(root.get("section_path"))
            and unit(n["payload"].get("section_path")) == unit(root.get("section_path"))
            and set(n["references"]) & active
        ]
        linked = {n["point_id"]: n for n in direct + inverse}
        new = [n for key, n in linked.items() if key not in selected]
        selected.update(linked)
        steps.append(
            {
                "round": number,
                "frontier": sorted(active),
                "outbound": sorted(outgoing),
                "new_chunks": [
                    {
                        "point_id": n["point_id"],
                        "own": n["own"],
                        "references": n["references"],
                        "outside_root_unit": unit(n["payload"].get("section_path"))
                        != unit(root.get("section_path")),
                    }
                    for n in new
                ],
            }
        )
        active.update(a for n in linked.values() for a in n["own"])
    records = [n for n in nodes if n["point_id"] in selected]
    all_present = {a for n in records for a in n["own"]}
    pending = {ref for n in records for ref in n["references"]} - all_present
    external = {ref for n in records for ref in n["external_references"]}
    return {
        "records": records,
        "audit": {
            "document_id": root["document_id"],
            "scope_identity": {
                k: root.get(k)
                for k in (
                    "organisation_id",
                    "source_type",
                    "instrument_id",
                    "effective_from",
                    "effective_to",
                    "instrument_status",
                )
            },
            "root_articles": root["article_nums"],
            "unit": unit(root.get("section_path")),
            "ambiguous_article_versions_not_resolved": sorted(ambiguous),
            "rounds": steps,
            "unresolved_or_not_expanded_references": sorted(pending),
            "external_instrument_references_not_resolved": sorted(external),
        },
    }


def _read_instrument(qdrant, root, organisation_id, org_idcc_list):
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from app.rag.access_filter import build_org_access_filter
    from app.rag.qdrant_store import COLLECTION_NAME

    must = [FieldCondition(key="document_id", match=MatchValue(value=root.document_id))]
    access = build_org_access_filter(organisation_id, org_idcc_list)
    if access is not None:
        must.append(access)
    if root.instrument_id:
        must.append(FieldCondition(key="instrument_id", match=MatchValue(value=root.instrument_id)))
    rows, offset, offsets, pages = [], None, set(), 0
    while True:
        points, offset = qdrant.scroll(
            COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            offset=offset,
            limit=512,
            with_payload=True,
            with_vectors=False,
        )
        rows.extend({"id": str(point.id), "payload": point.payload or {}} for point in points)
        pages += 1
        if offset is None:
            return rows, pages
        if str(offset) in offsets:
            from app.rag.parent_expansion import ParentExpansionError

            raise ParentExpansionError("reference_pagination_not_progressing")
        offsets.add(str(offset))


async def extend_reference_context(
    baseline,
    qdrant,
    *,
    organisation_id=None,
    org_idcc_list=None,
    diagnostics=None,
    candidate_roots=None,
):
    """Append intact explicit linked passages; never replace baseline parents.

    One highest-ranked candidate article with supported explicit identifiers supplies the
    starting point. Outgoing links stay within its document/instrument/version;
    inverse links stay within its local legal unit. Two exploration rounds are
    reported, including unresolved links. No new LLM, reranking or global cutoff.
    """
    import asyncio
    import time
    from dataclasses import asdict, replace

    from app.rag.parent_expansion import ParentExpansionError, _parent_key_for, _payload_to_result
    from app.rag.source_intent import CODE_SOURCE_LABELS

    if not baseline:
        return baseline
    root = next(
        (
            r
            for r in sorted(
                candidate_roots if candidate_roots is not None else baseline,
                key=lambda r: r.score,
                reverse=True,
            )
            if _parent_key_for(r)[0] == "article"
            and any(refs(a) == {norm(a)} for a in r.article_nums)
        ),
        None,
    )
    info = {"status": "reference_links", "starting_point": None, "added_passages": []}
    if diagnostics is not None:
        diagnostics.append(info)
    if root is None:
        info["reason"] = "no_selected_article_with_supported_reference"
        return baseline
    info["starting_point"] = {"document_id": root.document_id, "articles": root.article_nums}
    started = time.perf_counter()
    try:
        points, pages = await asyncio.to_thread(
            _read_instrument,
            qdrant,
            root,
            organisation_id,
            org_idcc_list,
        )
        graph = build_graph(
            asdict(root),
            points,
            rounds=2,
            scope_resolver=lambda text: explicit_reference_scopes(text, CODE_SOURCE_LABELS),
        )
    except Exception as exc:
        info.update(reason="reference_read_failed", error_type=type(exc).__name__)
        raise ParentExpansionError("reference_read_failed") from exc
    info.update(graph["audit"], points_consulted=len(points), pages=pages)
    # A passage already transmitted is never edited, removed or re-scored.
    seen = {
        (r.document_id, i) for r in baseline for i in (r.context_chunk_indices or [r.chunk_index])
    }
    groups = {}
    for node in graph["records"]:
        result = _payload_to_result(node["payload"])
        identity = (result.document_id, result.chunk_index)
        if identity in seen:
            continue
        seen.add(identity)
        groups.setdefault(_parent_key_for(result), []).append(result)
        info["added_passages"].append(
            {
                "point_id": node["point_id"],
                "document_id": result.document_id,
                "instrument_id": result.instrument_id,
                "article_id": result.article_id,
                "article_effective_from": result.article_effective_from,
                "article_effective_to": result.article_effective_to,
                "articles": result.article_nums,
                "chunk_index": result.chunk_index,
                "selection_reason": "explicit_reference_link",
            }
        )
    additions = []
    for chunks in groups.values():
        chunks.sort(key=lambda r: r.chunk_index)
        additions.append(
            replace(
                chunks[0],
                text="\n\n".join(r.text for r in chunks),
                article_nums=list(dict.fromkeys(a for r in chunks for a in r.article_nums or [])),
                context_chunk_indices=[r.chunk_index for r in chunks],
            )
        )
    info.update(added_groups=len(additions), seconds=time.perf_counter() - started)
    return [*baseline, *additions]
