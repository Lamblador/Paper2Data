"""Извлечение DOI из текста."""

from __future__ import annotations

import re

# Стандартный префикс DOI 10.xxxx/...
DOI_PATTERN = re.compile(
    r"""
    (?:doi\s*[:：]\s*|https?://(?:dx\.)?doi\.org/)?
    (?P<doi>10\.\d{4,9}/[^\s<>"']+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TRAILING_PUNCT = re.compile(r"[.,;:)\]]+$")


def normalize_doi(raw: str) -> str | None:
    if not raw:
        return None
    doi = raw.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi\s*[:：]\s*", "", doi, flags=re.I)
    doi = _TRAILING_PUNCT.sub("", doi)
    doi = doi.rstrip(".")
    if not re.match(r"^10\.\d{4,9}/.+", doi, re.I):
        return None
    return doi


def extract_dois(text: str) -> list[str]:
    """Все уникальные DOI в порядке появления."""
    found: list[str] = []
    seen: set[str] = set()
    for match in DOI_PATTERN.finditer(text or ""):
        doi = normalize_doi(match.group("doi"))
        if doi and doi.lower() not in seen:
            seen.add(doi.lower())
            found.append(doi)
    return found


def extract_first_doi(text: str) -> str | None:
    dois = extract_dois(text)
    return dois[0] if dois else None
