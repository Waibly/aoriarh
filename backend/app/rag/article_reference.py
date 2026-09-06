"""Canonical article spelling shared by ingestion and query parsing."""

import re


def normalize_article_reference(value: str) -> str:
    return re.sub(r"[.\s]", "", value).upper().replace("‑", "-").replace("–", "-")
