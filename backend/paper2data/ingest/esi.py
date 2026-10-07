"""Детекция ESI / Supporting Information и сверка названия с статьёй."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from paper2data.ingest.doi import extract_dois

_ESI_PHRASE = re.compile(
    r"""
    (?:
        supporting\s+information|
        supplementary\s+(?:information|data|material)s?|
        electronic\s+supporting\s+information|
        electronic\s+supplementary\s+(?:information|material)s?|
        \bESI\b|
        \bSI\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_URL = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)

_ESI_URL_HINT = re.compile(
    r"(supporting.?information|supplementary|esi|/si(?:/|$)|suppdata)",
    re.IGNORECASE,
)


def detect_esi_hints(text: str, *, max_snippets: int = 12) -> list[dict[str, Any]]:
    """
    Найти упоминания ESI: фразы, ссылки, DOI рядом с фразой.

    Возвращает список подсказок для UI-карточки.
    """
    hints: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(kind: str, value: str, snippet: str = "") -> None:
        key = f"{kind}:{value.strip().lower()}"
        if not value.strip() or key in seen:
            return
        seen.add(key)
        hints.append(
            {
                "kind": kind,  # phrase | url | doi
                "value": value.strip(),
                "snippet": snippet.strip()[:240],
            }
        )

    body = text or ""
    for match in _ESI_PHRASE.finditer(body):
        start = max(0, match.start() - 80)
        end = min(len(body), match.end() + 160)
        window = body[start:end]
        snippet = re.sub(r"\s+", " ", window)
        _add("phrase", match.group(0), snippet)

        for url in _URL.findall(window):
            clean = url.rstrip(".,);]")
            if _ESI_URL_HINT.search(clean):
                _add("url", clean, snippet)

        for doi in extract_dois(window):
            _add("doi", doi, snippet)

    for url in _URL.findall(body):
        clean = url.rstrip(".,);]")
        if _ESI_URL_HINT.search(clean):
            _add("url", clean, clean)

    return hints[:max_snippets]


# Греческие буквы в PDF часто становятся латинскими «похожими» (β → b).
_LOOKALIKES = str.maketrans(
    {
        "α": "a",
        "β": "b",
        "γ": "y",
        "δ": "d",
        "ε": "e",
        "μ": "u",
        "π": "p",
        "σ": "s",
        "ω": "w",
        "Α": "a",
        "Β": "b",
        "Γ": "y",
        "Δ": "d",
        "Ε": "e",
        "Μ": "u",
        "ß": "s",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def normalize_title(text: str) -> str:
    """Свести название к сравнимой строке: регистр, β/b, пунктуация, переносы."""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.translate(_LOOKALIKES)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^0-9a-zа-яё]+", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def titles_match(article_title: str, esi_title: str, *, threshold: float = 0.94) -> bool:
    """Совпадает ли название ESI с названием статьи."""
    left = normalize_title(article_title)
    right = normalize_title(esi_title)
    if len(left) < 15 or len(right) < 15:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold


class EsiTitleMismatch(ValueError):
    """PDF ESI не относится к этой статье."""

    def __init__(self, article_title: str, esi_title: str) -> None:
        self.article_title = article_title
        self.esi_title = esi_title
        super().__init__(
            "Название ESI не совпадает с названием статьи.\n"
            f"Статья: {article_title}\n"
            f"ESI: {esi_title or '—'}"
        )
