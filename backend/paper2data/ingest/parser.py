"""Парсер PDF → секции, блоки, таблицы, подписи, ссылки, ESI-подсказки."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf as fitz
import pdfplumber

from paper2data.ingest.captions import classify_caption
from paper2data.ingest.doi import extract_first_doi
from paper2data.ingest.esi import detect_esi_hints
from paper2data.ingest.sections import segment_blocks_by_headings


@dataclass
class ParsedBlock:
    block_type: str
    text: str
    page: int
    bbox: list[float] | None
    page_width: float
    page_height: float
    order_index: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedSection:
    section_type: str
    title: str
    page_start: int
    page_end: int
    useful_default: bool
    order_index: int
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass
class ParsedReference:
    raw_text: str
    doi: str | None
    page: int | None
    order_index: int


@dataclass
class ParseResult:
    title: str
    doi: str | None
    page_count: int
    sha256: str
    sections: list[ParsedSection]
    references: list[ParsedReference]
    esi_hints: list[dict[str, Any]]
    full_text: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_heading_like_font(span_size: float, page_median: float) -> bool:
    return span_size >= page_median * 1.15 or span_size >= 12.5


def _extract_pymupdf_blocks(doc: fitz.Document) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    order = 0
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        page_dict = page.get_text("dict")
        sizes: list[float] = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sizes.append(float(span.get("size") or 0))
        median = sorted(sizes)[len(sizes) // 2] if sizes else 10.0

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines_text: list[str] = []
            max_size = 0.0
            for line in block.get("lines", []):
                parts = [str(span.get("text") or "") for span in line.get("spans", [])]
                line_text = "".join(parts).strip()
                if line_text:
                    lines_text.append(line_text)
                for span in line.get("spans", []):
                    max_size = max(max_size, float(span.get("size") or 0))
            text = re.sub(r"[ \t]+", " ", "\n".join(lines_text)).strip()
            if not text:
                continue
            bbox = [float(x) for x in block.get("bbox", (0, 0, 0, 0))]
            raw.append(
                {
                    "text": text,
                    "page": page_index + 1,
                    "bbox": bbox,
                    "page_width": page_width,
                    "page_height": page_height,
                    "order_index": order,
                    "is_large_font": _is_heading_like_font(max_size, median),
                }
            )
            order += 1
    return raw


def _extract_tables(path: Path) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_width = float(page.width)
            page_height = float(page.height)
            found = page.extract_tables() or []
            # find_tables даёт bbox
            table_objs = []
            try:
                table_objs = page.find_tables() or []
            except Exception:  # noqa: BLE001
                table_objs = []

            for t_idx, rows in enumerate(found):
                if not rows:
                    continue
                clean_rows: list[list[str]] = []
                for row in rows:
                    clean_rows.append(
                        [re.sub(r"\s+", " ", (cell or "").strip()) for cell in row]
                    )
                bbox = None
                if t_idx < len(table_objs):
                    bb = table_objs[t_idx].bbox  # x0, top, x1, bottom (from top)
                    bbox = [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]
                md_lines = []
                if clean_rows:
                    header = clean_rows[0]
                    md_lines.append("| " + " | ".join(header) + " |")
                    md_lines.append("| " + " | ".join("---" for _ in header) + " |")
                    for row in clean_rows[1:]:
                        md_lines.append("| " + " | ".join(row) + " |")
                tables.append(
                    {
                        "page": page_index + 1,
                        "bbox": bbox,
                        "page_width": page_width,
                        "page_height": page_height,
                        "rows": clean_rows,
                        "markdown": "\n".join(md_lines),
                        "n_rows": len(clean_rows),
                        "n_cols": max((len(r) for r in clean_rows), default=0),
                    }
                )
    return tables


def _parse_references(section_blocks: list[ParsedBlock]) -> list[ParsedReference]:
    if not section_blocks:
        return []
    # Пропускаем заголовок секции
    texts = []
    page = section_blocks[0].page
    for i, block in enumerate(section_blocks):
        if i == 0 and classify_caption(block.text) is None:
            # возможно заголовок References
            from paper2data.ingest.sections import classify_heading

            if classify_heading(block.text):
                continue
        texts.append(block.text)
        page = block.page
    blob = "\n".join(texts)
    parts = re.split(r"\n(?=\[?\d+\]?[.)]\s)", blob)
    if len(parts) == 1:
        parts = re.split(r"(?=\b\d{1,3}\.\s+[A-Z])", blob)
    refs: list[ParsedReference] = []
    order = 0
    for part in parts:
        raw = re.sub(r"\s+", " ", part).strip()
        if len(raw) < 20:
            continue
        refs.append(
            ParsedReference(
                raw_text=raw,
                doi=extract_first_doi(raw),
                page=page,
                order_index=order,
            )
        )
        order += 1
    return refs


def _title_from_page(page: fitz.Page) -> str:
    """Название — самый крупный связный текст в верхней части первой страницы.

    Колонтитул журнала бывает крупнее, но короткий. Боковая колонка не разрывает
    строки названия: группируем по размеру шрифта, а не по порядку всех строк.
    """
    height = float(page.rect.height) or 1.0
    lines: list[tuple[float, float, str]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            text = "".join(str(span.get("text") or "") for span in spans).strip()
            if not text:
                continue
            size = max((float(span.get("size") or 0) for span in spans), default=0.0)
            y0 = float((line.get("bbox") or (0, 0, 0, 0))[1])
            if y0 <= height * 0.5 and size >= 11:
                lines.append((y0, size, text))
    if not lines:
        return ""
    lines.sort(key=lambda item: item[0])

    # Размер шрифта с допуском 0.8 pt — отдельные группы.
    groups: list[list[tuple[float, float, str]]] = []
    for item in lines:
        placed = False
        for group in groups:
            if abs(item[1] - group[0][1]) <= 0.8:
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    candidates: list[tuple[float, str]] = []
    for group in groups:
        group.sort(key=lambda item: item[0])
        chunks: list[list[str]] = [[]]
        prev_y: float | None = None
        size = group[0][1]
        for y0, _, text in group:
            if prev_y is not None and y0 - prev_y > size * 2.4:
                chunks.append([])
            chunks[-1].append(text)
            prev_y = y0
        for chunk in chunks:
            text = re.sub(r"\s+", " ", " ".join(chunk)).strip()
            if len(text) >= 40:
                candidates.append((size, text))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1][:500]


def extract_pdf_title(path: Path) -> str:
    """Название с первой страницы PDF."""
    path = Path(path)
    with fitz.open(path) as doc:
        if doc.page_count == 0:
            return ""
        return _title_from_page(doc[0])


def extract_pdf_title_bytes(data: bytes) -> str:
    """Название с первой страницы PDF из байтов."""
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.page_count == 0:
            return ""
        return _title_from_page(doc[0])


def _guess_title(blocks: list[dict[str, Any]], fallback: str) -> str:
    candidates = [
        b
        for b in blocks[:12]
        if b.get("page") == 1 and b.get("is_large_font") and len(str(b.get("text") or "")) > 10
    ]
    if candidates:
        return re.sub(r"\s+", " ", str(candidates[0]["text"]))[:500]
    for b in blocks[:8]:
        t = re.sub(r"\s+", " ", str(b.get("text") or "")).strip()
        if 15 <= len(t) <= 250 and not t.lower().startswith("abstract"):
            return t[:500]
    return fallback


def parse_pdf(path: Path, *, force_section_type: str | None = None) -> ParseResult:
    """Разобрать PDF. force_section_type='esi' — весь файл как ESI."""
    path = Path(path)
    sha = file_sha256(path)

    with fitz.open(path) as doc:
        page_count = len(doc)
        raw_blocks = _extract_pymupdf_blocks(doc)

    full_text = "\n\n".join(str(b["text"]) for b in raw_blocks)
    title = _guess_title(raw_blocks, fallback=path.stem)
    paper_doi = extract_first_doi("\n".join(str(b["text"]) for b in raw_blocks[:30]))
    esi_hints = [] if force_section_type == "esi" else detect_esi_hints(full_text)

    tables = _extract_tables(path)

    if force_section_type:
        section_specs = [
            {
                "section_type": force_section_type,
                "title": force_section_type.upper(),
                "page_start": 1,
                "page_end": page_count or 1,
                "useful_default": True,
                "block_indices": list(range(len(raw_blocks))),
            }
        ]
    else:
        section_specs = segment_blocks_by_headings(raw_blocks)

    # Индекс страниц, занятых таблицами — чтобы не дублировать текст таблиц как абзацы
    table_page_bboxes: list[tuple[int, list[float]]] = []
    for t in tables:
        if t.get("bbox"):
            table_page_bboxes.append((int(t["page"]), list(t["bbox"])))

    def _overlaps_table(page: int, bbox: list[float] | None) -> bool:
        if not bbox:
            return False
        for t_page, t_bbox in table_page_bboxes:
            if t_page != page:
                continue
            # IoU-ish overlap on y-range
            x_overlap = min(bbox[2], t_bbox[2]) - max(bbox[0], t_bbox[0])
            y_overlap = min(bbox[3], t_bbox[3]) - max(bbox[1], t_bbox[1])
            if x_overlap > 0 and y_overlap > 0:
                area = max(1.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
                if (x_overlap * y_overlap) / area > 0.4:
                    return True
        return False

    parsed_sections: list[ParsedSection] = []
    global_order = 0

    for s_idx, spec in enumerate(section_specs):
        section = ParsedSection(
            section_type=str(spec["section_type"]),
            title=str(spec.get("title") or ""),
            page_start=int(spec["page_start"]),
            page_end=int(spec["page_end"]),
            useful_default=bool(spec["useful_default"]),
            order_index=s_idx,
        )
        for b_idx in spec["block_indices"]:
            raw = raw_blocks[b_idx]
            bbox = list(raw["bbox"]) if raw.get("bbox") else None
            if _overlaps_table(int(raw["page"]), bbox):
                continue
            text = str(raw["text"])
            caption = classify_caption(text)
            block_type = "caption" if caption else "paragraph"
            meta: dict[str, Any] = {}
            if caption:
                meta = {"caption_kind": caption.kind, "caption_label": caption.label}
            section.blocks.append(
                ParsedBlock(
                    block_type=block_type,
                    text=text,
                    page=int(raw["page"]),
                    bbox=bbox,
                    page_width=float(raw["page_width"]),
                    page_height=float(raw["page_height"]),
                    order_index=global_order,
                    meta=meta,
                )
            )
            global_order += 1

        # Таблицы, попадающие в диапазон страниц секции
        for t in tables:
            page = int(t["page"])
            if page < section.page_start or page > section.page_end:
                continue
            # Привязка: если секций несколько overlapping — к первой подходящей
            # помечаем использованные таблицы
            if t.get("_used"):
                continue
            # Для ESI / single section — все таблицы; иначе эвристика по страницам
            if len(section_specs) > 1:
                # таблица принадлежит секции, если страница внутри и нет более поздней секции,
                # начинающейся на этой же странице с меньшим order — упрощённо: page in range
                pass
            t["_used"] = True
            table_block = ParsedBlock(
                block_type="table",
                text=str(t.get("markdown") or ""),
                page=page,
                bbox=t.get("bbox"),
                page_width=float(t["page_width"]),
                page_height=float(t["page_height"]),
                order_index=global_order,
                meta={
                    "n_rows": t["n_rows"],
                    "n_cols": t["n_cols"],
                    "rows": t["rows"],
                },
            )
            section.blocks.append(table_block)
            global_order += 1
            rows = t.get("rows") or []
            for r_i, row in enumerate(rows):
                for c_i, cell in enumerate(row):
                    cell_text = str(cell or "").strip()
                    if not cell_text:
                        continue
                    section.blocks.append(
                        ParsedBlock(
                            block_type="table_cell",
                            text=cell_text,
                            page=page,
                            bbox=t.get("bbox"),
                            page_width=float(t["page_width"]),
                            page_height=float(t["page_height"]),
                            order_index=global_order,
                            meta={
                                "row": r_i,
                                "col": c_i,
                                "parent_order": table_block.order_index,
                            },
                        )
                    )
                    global_order += 1

        parsed_sections.append(section)

    # Неиспользованные таблицы → other / последняя секция
    leftover = [t for t in tables if not t.get("_used")]
    if leftover:
        if not parsed_sections:
            parsed_sections.append(
                ParsedSection(
                    section_type=force_section_type or "other",
                    title="",
                    page_start=1,
                    page_end=page_count or 1,
                    useful_default=True,
                    order_index=0,
                )
            )
        target = parsed_sections[-1]
        for t in leftover:
            page = int(t["page"])
            table_block = ParsedBlock(
                block_type="table",
                text=str(t.get("markdown") or ""),
                page=page,
                bbox=t.get("bbox"),
                page_width=float(t["page_width"]),
                page_height=float(t["page_height"]),
                order_index=global_order,
                meta={
                    "n_rows": t["n_rows"],
                    "n_cols": t["n_cols"],
                    "rows": t["rows"],
                },
            )
            target.blocks.append(table_block)
            global_order += 1

    references: list[ParsedReference] = []
    for section in parsed_sections:
        if section.section_type == "references":
            references.extend(_parse_references(section.blocks))

    # DOI статьи: также из ссылок не берём — только начало текста
    if not paper_doi:
        paper_doi = extract_first_doi(full_text[:4000])

    return ParseResult(
        title=title,
        doi=paper_doi,
        page_count=page_count,
        sha256=sha,
        sections=parsed_sections,
        references=references,
        esi_hints=esi_hints,
        full_text=full_text,
    )
