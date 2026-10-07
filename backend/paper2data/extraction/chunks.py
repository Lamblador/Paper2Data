"""Чанкование секций, таблицы → Markdown, контекст для промптов."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.db.models import Block, Document, Section


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def serialize_block(block: Block) -> dict[str, Any]:
    return {
        "id": block.id,
        "section_id": block.section_id,
        "kind": block.kind,
        "text": block.text or "",
        "page": block.page,
        "bbox": _loads(block.bbox_json, None),
        "page_width": block.page_width,
        "page_height": block.page_height,
        "order_index": block.order_index,
        "meta": _loads(block.meta_json, {}),
    }


def load_document_blocks(
    session: Session,
    document_id: int,
    *,
    section_include: list[str] | None = None,
    section_exclude: list[str] | None = None,
    useful_only: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Возвращает (paragraph_blocks, table_mds, caption_blocks) с учётом фильтров секций."""
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"Документ не найден: {document_id}")

    include = set(section_include or [])
    exclude = set(section_exclude or [])

    sections = session.scalars(
        select(Section)
        .where(Section.document_id == document_id)
        .options(selectinload(Section.blocks))
        .order_by(Section.order_index)
    ).all()

    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []

    for section in sections:
        st = section.section_type
        if exclude and st in exclude:
            continue
        if include and st not in include:
            continue
        if useful_only and not section.useful and st not in include:
            continue
        # references всегда вне чанков извлечения фактов
        if st == "references" and (not include or "references" not in include):
            continue

        blocks = sorted(section.blocks or [], key=lambda b: b.order_index)
        for block in blocks:
            item = serialize_block(block)
            item["section_type"] = st
            item["section_title"] = section.title
            if block.kind == "table":
                tables.append(item)
            elif block.kind == "caption":
                captions.append(item)
            elif block.kind == "table_cell":
                continue
            else:
                paragraphs.append(item)

    return paragraphs, tables, captions


def table_block_to_markdown(block: dict[str, Any]) -> str:
    """Таблица как Markdown; если есть structured rows в meta — используем их."""
    meta = block.get("meta") or {}
    rows = meta.get("rows") or meta.get("markdown_rows")
    table_id = block.get("id")
    header = f"<!-- table_id={table_id} page={block.get('page')} -->\n"
    if isinstance(rows, list) and rows:
        # rows: list[list[str]] или list[dict]
        if rows and isinstance(rows[0], dict):
            keys = list(rows[0].keys())
            lines = [
                "| " + " | ".join(keys) + " |",
                "| " + " | ".join("---" for _ in keys) + " |",
            ]
            for r in rows:
                lines.append("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")
            return header + "\n".join(lines)
        # list of lists
        lines = []
        for i, row in enumerate(rows):
            cells = [str(c) for c in row]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in cells) + " |")
        return header + "\n".join(lines)

    text = (block.get("text") or "").strip()
    if text:
        return header + text
    return header + "_(пустая таблица)_"


def build_section_text(paragraphs: list[dict[str, Any]], *, max_chars: int | None = None) -> str:
    parts: list[str] = []
    total = 0
    current_section = None
    for b in paragraphs:
        st = b.get("section_type")
        if st != current_section:
            current_section = st
            title = b.get("section_title") or st or "section"
            header = f"\n## [{st}] {title}\n"
            parts.append(header)
            total += len(header)
        chunk = f"[block:{b['id']} p.{b.get('page')}]\n{b.get('text') or ''}\n"
        if max_chars is not None and total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining > 80:
                parts.append(chunk[:remaining] + "\n…[обрезано]\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts).strip()


def build_tables_md(tables: list[dict[str, Any]], *, max_chars: int | None = None) -> str:
    parts: list[str] = []
    total = 0
    for t in tables:
        md = table_block_to_markdown(t) + "\n\n"
        if max_chars is not None and total + len(md) > max_chars:
            break
        parts.append(md)
        total += len(md)
    return "".join(parts).strip()


def build_figure_captions(captions: list[dict[str, Any]]) -> str:
    lines = []
    for c in captions:
        lines.append(f"- [block:{c['id']} p.{c.get('page')}] {c.get('text') or ''}")
    return "\n".join(lines)


def chunk_by_sections(
    paragraphs: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    *,
    context_size: int = 128000,
    reserve_tokens_approx: int = 12000,
    pack_chunks: bool = True,
) -> list[dict[str, Any]]:
    """Группирует полезный текст по секциям с учётом грубого лимита символов (~3 char/token).

    pack_chunks=False оставляет секции отдельными запросами (без склейки ESI+experimental).
    """
    char_budget = max(4000, (context_size - reserve_tokens_approx) * 3)
    by_section: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for b in paragraphs:
        key = str(b.get("section_type") or "other")
        if key not in by_section:
            by_section[key] = {
                "section_type": key,
                "paragraphs": [],
                "tables": [],
                "captions": [],
            }
            order.append(key)
        by_section[key]["paragraphs"].append(b)
    for t in tables:
        key = str(t.get("section_type") or "other")
        if key not in by_section:
            by_section[key] = {
                "section_type": key,
                "paragraphs": [],
                "tables": [],
                "captions": [],
            }
            order.append(key)
        by_section[key]["tables"].append(t)
    for c in captions:
        key = str(c.get("section_type") or "other")
        if key not in by_section:
            by_section[key] = {
                "section_type": key,
                "paragraphs": [],
                "tables": [],
                "captions": [],
            }
            order.append(key)
        by_section[key]["captions"].append(c)

    chunks: list[dict[str, Any]] = []
    for key in order:
        bucket = by_section[key]
        # Если секция слишком длинная — режем параграфы на подчанки
        paras = bucket["paragraphs"]
        if not paras and not bucket["tables"]:
            continue
        start = 0
        while start < len(paras) or (start == 0 and bucket["tables"]):
            slice_paras = []
            size = 0
            i = start
            while i < len(paras):
                tlen = len(paras[i].get("text") or "")
                if slice_paras and size + tlen > char_budget:
                    break
                slice_paras.append(paras[i])
                size += tlen
                i += 1
            include_tables = bucket["tables"] if start == 0 else []
            include_caps = bucket["captions"] if start == 0 else []
            chunks.append(
                {
                    "section_type": key,
                    "section_text": build_section_text(slice_paras, max_chars=char_budget),
                    "tables_md": build_tables_md(include_tables, max_chars=char_budget // 2),
                    "figure_captions": build_figure_captions(include_caps),
                    "block_ids": [p["id"] for p in slice_paras]
                    + [t["id"] for t in include_tables]
                    + [c["id"] for c in include_caps],
                    "blocks": slice_paras + include_tables + include_caps,
                }
            )
            if i <= start:
                # защита от бесконечного цикла на гигантском блоке
                if i < len(paras):
                    i += 1
                else:
                    break
            start = i
            if not paras:
                break
    if not pack_chunks:
        return chunks
    return pack_chunks_to_context(
        chunks,
        context_size=context_size,
        reserve_tokens_approx=reserve_tokens_approx,
    )


def _chunk_payload_size(chunk: dict[str, Any]) -> int:
    return (
        len(chunk.get("section_text") or "")
        + len(chunk.get("tables_md") or "")
        + len(chunk.get("figure_captions") or "")
    )


def merge_chunk_group(chunks: list[dict[str, Any]], *, section_type: str = "document") -> dict[str, Any]:
    """Склеивает несколько секционных чанков в один запрос к модели."""
    if len(chunks) == 1:
        return chunks[0]
    text_parts: list[str] = []
    tables_parts: list[str] = []
    caps_parts: list[str] = []
    block_ids: list[Any] = []
    blocks: list[dict[str, Any]] = []
    types: list[str] = []
    for c in chunks:
        st = str(c.get("section_type") or "other")
        types.append(st)
        body = (c.get("section_text") or "").strip()
        if body:
            text_parts.append(f"### Секция: {st}\n{body}")
        tables = (c.get("tables_md") or "").strip()
        if tables:
            tables_parts.append(tables)
        caps = (c.get("figure_captions") or "").strip()
        if caps:
            caps_parts.append(caps)
        block_ids.extend(c.get("block_ids") or [])
        blocks.extend(c.get("blocks") or [])
    return {
        "section_type": section_type if len(set(types)) > 1 else (types[0] if types else section_type),
        "section_text": "\n\n".join(text_parts),
        "tables_md": "\n\n".join(tables_parts),
        "figure_captions": "\n".join(caps_parts),
        "block_ids": block_ids,
        "blocks": blocks,
        "merged_sections": types,
    }


def pack_chunks_to_context(
    chunks: list[dict[str, Any]],
    *,
    context_size: int,
    reserve_tokens_approx: int = 12000,
) -> list[dict[str, Any]]:
    """Если выбранные секции влезают в контекст — один чанк на всю статью (фильтр секций).

    Иначе пакует соседние секции в минимальное число запросов.
    """
    if len(chunks) <= 1:
        return chunks
    char_budget = max(4000, (context_size - reserve_tokens_approx) * 3)
    total = sum(_chunk_payload_size(c) for c in chunks)
    if total <= char_budget:
        return [merge_chunk_group(chunks, section_type="document")]

    packed: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for chunk in chunks:
        csize = _chunk_payload_size(chunk)
        if current and size + csize > char_budget:
            packed.append(merge_chunk_group(current))
            current = []
            size = 0
        current.append(chunk)
        size += csize
    if current:
        packed.append(merge_chunk_group(current))
    return packed


def full_document_text(session: Session, document_id: int) -> str:
    blocks = session.scalars(
        select(Block)
        .where(Block.document_id == document_id)
        .order_by(Block.order_index)
    ).all()
    return "\n".join(b.text or "" for b in blocks)
