"""Верификация цитат: fuzzy-поиск в тексте документа (rapidfuzz ≥ threshold)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from rapidfuzz import fuzz


DEFAULT_QUOTE_THRESHOLD = 90
_ELLIPSIS = re.compile(r"\.{3,}|…")


@dataclass
class QuoteMatch:
    verified: bool
    score: float
    matched_text: str | None = None
    block_id: int | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None


def normalize_quote(text: str) -> str:
    return " ".join((text or "").split()).strip()


def verify_quote_in_text(
    quote: str,
    document_text: str,
    *,
    threshold: float = DEFAULT_QUOTE_THRESHOLD,
) -> QuoteMatch:
    """Проверяет, что quote встречается в document_text с score ≥ threshold."""
    q = normalize_quote(quote)
    if not q:
        return QuoteMatch(verified=False, score=0.0)
    corpus = document_text or ""
    if not corpus.strip():
        return QuoteMatch(verified=False, score=0.0)

    # Точное вхождение после нормализации пробелов
    norm_corpus = normalize_quote(corpus)
    if q in norm_corpus:
        return QuoteMatch(verified=True, score=100.0, matched_text=q)

    # partial_ratio хорошо ловит цитату как подстроку длинного текста
    score = float(fuzz.partial_ratio(q, corpus))
    if score >= threshold:
        return QuoteMatch(verified=True, score=score, matched_text=q)

    # Скользящее окно по длине цитаты (±20%)
    window = max(len(q), 8)
    best = 0.0
    best_slice: str | None = None
    step = max(1, window // 4)
    for i in range(0, max(1, len(corpus) - window + 1), step):
        chunk = corpus[i : i + int(window * 1.2)]
        s = float(fuzz.ratio(q, normalize_quote(chunk)))
        if s > best:
            best = s
            best_slice = chunk
            if best >= 99.0:
                break
    if best >= threshold:
        return QuoteMatch(verified=True, score=best, matched_text=normalize_quote(best_slice or q))
    return QuoteMatch(verified=False, score=max(score, best), matched_text=None)


def char_span(quote: str, text: str) -> tuple[int | None, int | None]:
    """Позиция цитаты в тексте блока, если она входит дословно."""
    q = normalize_quote(quote)
    if not q or not text:
        return None, None
    pos = text.lower().find(q.lower())
    if pos < 0:
        return None, None
    return pos, pos + len(q)


def score_quote_in_block(quote: str, block_text: str) -> float:
    """Насколько цитата содержится в блоке.

    partial_ratio(длинная цитата, текст «3») даёт 100, если эта цифра
    просто встречается в цитате. Короткие блоки вроде номера страницы
    поэтому отбрасываются: ищем цитату внутри блока, а не блок внутри цитаты.
    """
    q = normalize_quote(quote)
    b = normalize_quote(block_text)
    if not q or not b or len(b) < 8:
        return 0.0

    parts = [normalize_quote(part) for part in _ELLIPSIS.split(quote or "")]
    parts = [part for part in parts if len(part) >= 4]
    if len(parts) >= 2:
        folded = b.lower()
        cursor = 0
        found_all = True
        for part in parts:
            idx = folded.find(part.lower(), cursor)
            if idx < 0:
                found_all = False
                break
            cursor = idx + len(part)
        if found_all:
            return 100.0

    if len(b) < max(8, int(len(q) * 0.75)):
        return 0.0
    if q.lower() in b.lower():
        return 100.0
    return float(fuzz.partial_ratio(q, b))


def verify_quote_against_blocks(
    quote: str,
    blocks: Sequence[dict],
    *,
    threshold: float = DEFAULT_QUOTE_THRESHOLD,
) -> QuoteMatch:
    """Ищет цитату среди блоков; выбирает лучший match."""
    q = normalize_quote(quote)
    if not q:
        return QuoteMatch(verified=False, score=0.0)
    if not blocks:
        return QuoteMatch(verified=False, score=0.0)

    best_score = 0.0
    best_idx: int | None = None
    for idx, block in enumerate(blocks):
        score = score_quote_in_block(q, str(block.get("text") or ""))
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx is None:
        return QuoteMatch(verified=False, score=0.0)

    block = blocks[best_idx]
    block_text = str(block.get("text") or "")
    verified = best_score >= threshold
    char_start, char_end = char_span(q, block_text)
    return QuoteMatch(
        verified=verified,
        score=best_score,
        matched_text=q if verified else None,
        block_id=block.get("id"),
        page=block.get("page"),
        char_start=char_start,
        char_end=char_end,
    )
