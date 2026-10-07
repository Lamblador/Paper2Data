"""Crossref lookup по DOI для Paper / Reference."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from paper2data.ingest.doi import normalize_doi

CROSSREF_WORKS_BASE = "https://api.crossref.org/works"


def crossref_works_url(doi: str) -> str:
    """Канонический URL запроса Crossref works/{doi}."""
    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError(f"Некорректный DOI: {doi!r}")
    return f"{CROSSREF_WORKS_BASE}/{quote(normalized, safe='')}"


def _authors_short(message: dict[str, Any]) -> str | None:
    authors = message.get("author") or []
    if not authors:
        return None
    parts: list[str] = []
    for a in authors[:4]:
        family = a.get("family") or ""
        given = a.get("given") or ""
        if family and given:
            parts.append(f"{family} {given[0]}.")
        elif family:
            parts.append(family)
        elif given:
            parts.append(given)
    if len(authors) > 4:
        parts.append("et al.")
    return ", ".join(parts) if parts else None


def _title(message: dict[str, Any]) -> str | None:
    titles = message.get("title") or []
    if titles:
        return str(titles[0])
    return None


def lookup_doi(doi: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Метаданные работы по DOI через Crossref REST."""
    try:
        url = crossref_works_url(doi)
    except ValueError as exc:
        return {"ok": False, "doi": doi, "error": str(exc)}

    normalized = normalize_doi(doi)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": "Paper2Data/0.1 (mailto:local@paper2data; local app)",
                    "Accept": "application/json",
                },
            )
        if response.status_code == 404:
            return {
                "ok": False,
                "doi": normalized,
                "url": url,
                "error": "DOI не найден в Crossref",
            }
        if response.status_code >= 400:
            return {
                "ok": False,
                "doi": normalized,
                "url": url,
                "error": f"Crossref HTTP {response.status_code}: {response.text[:300]}",
            }
        payload = response.json()
        message = payload.get("message") or {}
        year = None
        issued = message.get("issued") or {}
        parts = (issued.get("date-parts") or [[]])[0]
        if parts:
            year = parts[0]
        container = (message.get("container-title") or [None])[0]
        return {
            "ok": True,
            "doi": normalized or message.get("DOI"),
            "url": url,
            "title": _title(message),
            "authors": _authors_short(message),
            "year": year,
            "container_title": container,
            "type": message.get("type"),
            "publisher": message.get("publisher"),
            "issn": (message.get("ISSN") or [None])[0],
            "raw_message_keys": sorted(message.keys())[:40],
            "needs_confirm": True,
            "suggested_attributes": {
                "doi": normalized or message.get("DOI"),
                "title": _title(message),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "doi": normalized,
            "url": url,
            "error": str(exc),
        }
