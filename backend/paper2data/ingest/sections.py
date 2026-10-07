"""Эвристики сегментации секций по заголовкам."""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from paper2data.db.models import SECTION_USEFUL_DEFAULT
except ImportError:  # pragma: no cover
    SECTION_USEFUL_DEFAULT = {
        "abstract": True,
        "introduction": False,
        "experimental": True,
        "results": True,
        "conclusion": True,
        "acknowledgments": False,
        "references": False,
        "esi": True,
        "other": True,
    }

# (section_type, compiled patterns) — порядок важен: более специфичные раньше
_HEADING_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "abstract",
        re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?abstract\b", re.I),
    ),
    (
        "introduction",
        re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?introduction\b", re.I),
    ),
    (
        "experimental",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?("
            r"experimental(?:\s+section)?|"
            r"materials?\s+and\s+methods?|"
            r"methods?(?:\s+and\s+materials?)?|"
            r"experimental\s+details|"
            r"synthesis|"
            r"computational\s+details"
            r")\b",
            re.I,
        ),
    ),
    (
        "results",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?("
            r"results?(?:\s+and\s+discussion)?|"
            r"discussion|"
            r"results?\s+and\s+analysis"
            r")\b",
            re.I,
        ),
    ),
    (
        "conclusion",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?("
            r"conclusions?|"
            r"concluding\s+remarks|"
            r"summary|"
            r"final\s+remarks"
            r")\b",
            re.I,
        ),
    ),
    (
        "acknowledgments",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?acknowledge?ments?\b",
            re.I,
        ),
    ),
    (
        "references",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?("
            r"references?|"
            r"bibliography|"
            r"literature\s+cited|"
            r"works?\s+cited"
            r")\b",
            re.I,
        ),
    ),
    (
        "esi",
        re.compile(
            r"^(?:\d+(?:\.\d+)*\.?\s+)?("
            r"supporting\s+information|"
            r"supplementary\s+(?:information|data|material)s?|"
            r"electronic\s+supporting\s+information|"
            r"esi\b"
            r")",
            re.I,
        ),
    ),
]

# Короткая строка-кандидат в заголовок
_MAX_HEADING_LEN = 120


@dataclass(frozen=True)
class HeadingMatch:
    section_type: str
    title: str


def normalize_heading_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def classify_heading(text: str) -> HeadingMatch | None:
    """Вернуть тип секции, если строка похожа на заголовок раздела."""
    cleaned = normalize_heading_text(text)
    if not cleaned or len(cleaned) > _MAX_HEADING_LEN:
        return None
    # Многоточие / слишком много слов — скорее абзац
    if cleaned.count(" ") > 14:
        return None
    for section_type, pattern in _HEADING_RULES:
        if pattern.search(cleaned):
            return HeadingMatch(section_type=section_type, title=cleaned)
    return None


def useful_default_for(section_type: str) -> bool:
    return SECTION_USEFUL_DEFAULT.get(section_type, True)


def segment_blocks_by_headings(
    blocks: list[dict],
) -> list[dict]:
    """
    Разбить упорядоченный список сырых блоков на секции.

    Каждый элемент blocks: {text, page, ...}.
    Возвращает секции: {section_type, title, page_start, page_end, useful_default, block_indices}.
    """
    if not blocks:
        return []

    headings: list[tuple[int, HeadingMatch]] = []
    for idx, block in enumerate(blocks):
        match = classify_heading(str(block.get("text") or ""))
        if match is not None:
            headings.append((idx, match))

    if not headings:
        pages = [int(b.get("page") or 1) for b in blocks]
        return [
            {
                "section_type": "other",
                "title": "",
                "page_start": min(pages) if pages else 1,
                "page_end": max(pages) if pages else 1,
                "useful_default": useful_default_for("other"),
                "block_indices": list(range(len(blocks))),
            }
        ]

    sections: list[dict] = []
    # Прелюдия до первого заголовка
    first_idx = headings[0][0]
    if first_idx > 0:
        prelude = blocks[:first_idx]
        pages = [int(b.get("page") or 1) for b in prelude]
        sections.append(
            {
                "section_type": "other",
                "title": "",
                "page_start": min(pages),
                "page_end": max(pages),
                "useful_default": useful_default_for("other"),
                "block_indices": list(range(0, first_idx)),
            }
        )

    for i, (start_idx, match) in enumerate(headings):
        end_idx = headings[i + 1][0] if i + 1 < len(headings) else len(blocks)
        slice_blocks = blocks[start_idx:end_idx]
        pages = [int(b.get("page") or 1) for b in slice_blocks] or [1]
        sections.append(
            {
                "section_type": match.section_type,
                "title": match.title,
                "page_start": min(pages),
                "page_end": max(pages),
                "useful_default": useful_default_for(match.section_type),
                "block_indices": list(range(start_idx, end_idx)),
            }
        )

    return sections
