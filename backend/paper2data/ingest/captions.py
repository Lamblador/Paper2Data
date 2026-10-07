"""Подписи рисунков / схем / таблиц."""

from __future__ import annotations

import re
from dataclasses import dataclass

CAPTION_PATTERN = re.compile(
    r"""
    ^\s*
    (?:
        (?P<kind_fig>fig(?:ure)?\.?) |
        (?P<kind_scheme>scheme\.?) |
        (?P<kind_table>tables?\.?)
    )
    \s*
    (?P<label>[S]?\d+[A-Za-z]?)
    \s*[.:)—–-]?\s*
    (?P<rest>.*)?
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True)
class CaptionMatch:
    kind: str  # figure | scheme | table
    label: str
    text: str


def classify_caption(text: str) -> CaptionMatch | None:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned or len(cleaned) > 2000:
        return None
    match = CAPTION_PATTERN.match(cleaned)
    if not match:
        return None
    if match.group("kind_fig"):
        kind = "figure"
    elif match.group("kind_scheme"):
        kind = "scheme"
    else:
        kind = "table"
    label = (match.group("label") or "").strip()
    return CaptionMatch(kind=kind, label=label, text=cleaned)
