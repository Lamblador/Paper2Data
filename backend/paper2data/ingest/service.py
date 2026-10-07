"""Индексация papers/, ingest в БД, прикрепление ESI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState
from paper2data.db.models import Block, DocFile, Document, Reference, Section
from paper2data.ingest.esi import EsiTitleMismatch, titles_match
from paper2data.ingest.parser import ParseResult, extract_pdf_title, extract_pdf_title_bytes, parse_pdf

_ESI_NAME = re.compile(r"(?:^|[_\-.])(?:esi|si|supporting|suppl)(?:[_\-.]|$)", re.I)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _merge_esi_hints(detected: list[Any], previous: list[Any]) -> list[Any]:
    """Подсказки из PDF плюс ссылки, которые пользователь добавил сам."""
    manual = [
        hint
        for hint in previous
        if isinstance(hint, dict) and hint.get("manual")
    ]
    seen: set[str] = set()
    unique: list[Any] = []
    for hint in list(detected) + manual:
        if not isinstance(hint, dict):
            continue
        key = f"{hint.get('kind')}:{str(hint.get('value') or '').strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(hint)
    return unique


def _load_document(session: Session, document_id: int) -> Document:
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.files),
            selectinload(Document.sections),
            selectinload(Document.blocks),
            selectinload(Document.references),
        )
    )
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")
    return document


def _article_title_for_esi(project: ProjectState, document: Document) -> str:
    main = next((f for f in document.files if f.role == "main"), None)
    if main is not None:
        path = _abs_from_rel(project, main.relative_path)
        if path.is_file():
            title = extract_pdf_title(path)
            if title:
                return title
    title = (document.title or "").strip()
    if len(title) >= 15:
        return title
    raise ValueError("Не удалось прочитать название статьи из основного PDF")


def _rel_to_papers(project: ProjectState, path: Path) -> str:
    return path.resolve().relative_to(project.papers_dir.resolve()).as_posix()


def _abs_from_rel(project: ProjectState, relative_path: str) -> Path:
    papers = project.papers_dir.resolve()
    path = (project.papers_dir / relative_path).resolve()
    path.relative_to(papers)
    return path


def _stem_key(path: Path) -> str:
    name = path.stem
    cleaned = _ESI_NAME.sub("_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower() or name.lower()


def _is_esi_filename(path: Path) -> bool:
    return bool(_ESI_NAME.search(path.stem))


def list_pdf_files(project: ProjectState) -> list[Path]:
    if not project.papers_dir.exists():
        return []
    return sorted(p for p in project.papers_dir.rglob("*.pdf") if p.is_file())


def index_papers(session: Session, project: ProjectState) -> list[Document]:
    """Создать Document + DocFile для новых PDF в papers/."""
    existing_paths = {
        df.relative_path for df in session.scalars(select(DocFile)).all()
    }
    docs_by_stem: dict[str, Document] = {
        d.source_stem: d
        for d in session.scalars(select(Document)).all()
        if d.source_stem
    }

    for pdf in list_pdf_files(project):
        rel = _rel_to_papers(project, pdf)
        if rel in existing_paths:
            continue

        role = "esi" if _is_esi_filename(pdf) else "main"
        stem = _stem_key(pdf)

        if role == "esi" and stem in docs_by_stem:
            doc = docs_by_stem[stem]
        elif role == "main":
            unique_stem = stem
            if unique_stem in docs_by_stem:
                unique_stem = f"{stem}__{pdf.stem.lower()}"
            doc = Document(
                title=pdf.stem,
                status="indexed",
                source_stem=unique_stem,
                source_path=rel,
            )
            session.add(doc)
            session.flush()
            docs_by_stem[unique_stem] = doc
        else:
            unique_stem = f"{stem}__esi"
            if unique_stem in docs_by_stem:
                unique_stem = f"{stem}__esi__{pdf.stem.lower()}"
            doc = Document(
                title=pdf.stem,
                status="indexed",
                source_stem=unique_stem,
                source_path=rel,
            )
            session.add(doc)
            session.flush()
            docs_by_stem[unique_stem] = doc

        session.add(
            DocFile(
                document_id=doc.id,
                role=role,
                relative_path=rel,
                filename=pdf.name,
            )
        )
        existing_paths.add(rel)

    session.flush()
    return list(
        session.scalars(
            select(Document).options(selectinload(Document.files)).order_by(Document.id)
        ).all()
    )


def _clear_parsed_content(
    session: Session,
    document: Document,
    *,
    only_doc_file_id: int | None = None,
) -> None:
    if only_doc_file_id is None:
        for section in list(document.sections):
            session.delete(section)
        for ref in list(document.references):
            session.delete(ref)
        for block in list(document.blocks):
            session.delete(block)
        session.flush()
        return

    sections = [s for s in document.sections if s.doc_file_id == only_doc_file_id]
    section_ids = {s.id for s in sections}
    for block in list(document.blocks):
        if block.section_id in section_ids:
            session.delete(block)
    for section in sections:
        session.delete(section)
    session.flush()


def _persist_parse(
    session: Session,
    document: Document,
    doc_file: DocFile,
    result: ParseResult,
    *,
    replace_all: bool,
) -> None:
    if replace_all:
        _clear_parsed_content(session, document)
    else:
        _clear_parsed_content(session, document, only_doc_file_id=doc_file.id)

    doc_file.page_count = result.page_count
    doc_file.sha256 = result.sha256

    if doc_file.role == "main":
        if result.title:
            document.title = result.title
        if result.doi:
            document.doi = result.doi
        previous_hints = _loads(document.esi_hints_json, [])
        document.esi_hints_json = _dumps(
            _merge_esi_hints(result.esi_hints, previous_hints)
        )
        meta = _loads(document.meta_json, {})
        meta["page_count"] = result.page_count
        document.meta_json = _dumps(meta)
        document.source_path = doc_file.relative_path

    for section in result.sections:
        db_section = Section(
            document_id=document.id,
            doc_file_id=doc_file.id,
            section_type=section.section_type,
            title=section.title or None,
            page_start=section.page_start,
            page_end=section.page_end,
            useful=section.useful_default,
            order_index=section.order_index,
        )
        session.add(db_section)
        session.flush()
        for block in section.blocks:
            session.add(
                Block(
                    document_id=document.id,
                    section_id=db_section.id,
                    kind=block.block_type,
                    text=block.text,
                    page=block.page,
                    bbox_json=_dumps(block.bbox) if block.bbox else None,
                    page_width=block.page_width,
                    page_height=block.page_height,
                    order_index=block.order_index,
                    meta_json=_dumps(block.meta or {}),
                )
            )

    if doc_file.role == "main":
        for ref in result.references:
            session.add(
                Reference(
                    document_id=document.id,
                    raw_text=ref.raw_text,
                    doi=ref.doi,
                    page=ref.page,
                    order_index=ref.order_index,
                )
            )


def ingest_document(session: Session, project: ProjectState, document_id: int) -> Document:
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.files),
            selectinload(Document.sections),
            selectinload(Document.blocks),
            selectinload(Document.references),
        )
    )
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")

    document.status = "parsing"
    document.error_message = None
    session.flush()

    try:
        main = next((f for f in document.files if f.role == "main"), None)
        if main is None and document.source_path:
            src = Path(document.source_path)
            candidate: Path | None = None
            if src.is_file():
                candidate = src
            else:
                try:
                    candidate = _abs_from_rel(project, document.source_path)
                except ValueError:
                    candidate = None
            if candidate is not None and candidate.is_file():
                rel = _rel_to_papers(project, candidate)
                main = DocFile(
                    document_id=document.id,
                    role="main",
                    relative_path=rel,
                    filename=candidate.name,
                )
                session.add(main)
                session.flush()
                document.files.append(main)

        if main is None:
            raise FileNotFoundError("Нет основного PDF (role=main)")

        main_path = _abs_from_rel(project, main.relative_path)
        if not main_path.is_file():
            raise FileNotFoundError(f"Файл не найден: {main.relative_path}")

        result = parse_pdf(main_path)
        _persist_parse(session, document, main, result, replace_all=True)

        for esi_file in [f for f in document.files if f.role == "esi"]:
            esi_path = _abs_from_rel(project, esi_file.relative_path)
            if not esi_path.is_file():
                continue
            esi_result = parse_pdf(esi_path, force_section_type="esi")
            _persist_parse(session, document, esi_file, esi_result, replace_all=False)

        document.status = "parsed"
        document.error_message = None

        # M5: извлечение рисунков после успешного ingest (ошибка не ломает разбор текста)
        try:
            from paper2data.figures import service as figures_service

            figures_service.extract_and_store_figures(
                session, project, document.id, replace=True, auto_classify=True
            )
        except Exception:  # noqa: BLE001
            meta = _loads(document.meta_json, {})
            meta["figures_extract_error"] = "extract_failed"
            document.meta_json = _dumps(meta)
    except Exception as exc:  # noqa: BLE001
        document.status = "error"
        document.error_message = str(exc)
        raise

    session.flush()
    return document


def upload_pdf(
    session: Session,
    project: ProjectState,
    filename: str,
    data: bytes,
    *,
    as_esi_for: int | None = None,
) -> Document:
    safe_name = Path(filename).name
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    dest = project.papers_dir / safe_name
    if dest.exists():
        stem, suf = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = project.papers_dir / f"{stem}_{i}{suf}"
            i += 1
    dest.write_bytes(data)
    rel = _rel_to_papers(project, dest)

    if as_esi_for is not None:
        document = session.get(Document, as_esi_for)
        if document is None:
            raise KeyError(f"Документ {as_esi_for} не найден")
        session.add(
            DocFile(
                document_id=document.id,
                role="esi",
                relative_path=rel,
                filename=dest.name,
            )
        )
        session.flush()
        return document

    role = "esi" if _is_esi_filename(dest) else "main"
    stem = _stem_key(dest) if role == "main" else f"{_stem_key(dest)}__esi"
    document = Document(
        title=dest.stem,
        status="indexed",
        source_stem=stem,
        source_path=rel,
    )
    session.add(document)
    session.flush()
    session.add(
        DocFile(
            document_id=document.id,
            role=role,
            relative_path=rel,
            filename=dest.name,
        )
    )
    session.flush()
    return document


def attach_esi_file(
    session: Session,
    project: ProjectState,
    document_id: int,
    filename: str,
    data: bytes,
    *,
    ingest: bool = True,
) -> Document:
    document = _load_document(session, document_id)
    article_title = _article_title_for_esi(project, document)
    try:
        esi_title = extract_pdf_title_bytes(data)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Не удалось прочитать PDF ESI") from exc
    if not esi_title:
        raise ValueError("Не удалось прочитать название из файла ESI")
    if not titles_match(article_title, esi_title):
        raise EsiTitleMismatch(article_title, esi_title)

    upload_pdf(session, project, filename, data, as_esi_for=document_id)
    session.expire_all()
    document = _load_document(session, document_id)

    esi_files = [f for f in document.files if f.role == "esi"]
    esi_file = max(esi_files, key=lambda f: f.id) if esi_files else None
    if ingest and esi_file is not None:
        path = _abs_from_rel(project, esi_file.relative_path)
        result = parse_pdf(path, force_section_type="esi")
        _persist_parse(session, document, esi_file, result, replace_all=False)
        if document.status in ("indexed", "new", "error"):
            document.status = "parsed"
    saved_name = esi_file.filename if esi_file is not None else Path(filename).name
    meta = _loads(document.meta_json, {})
    meta["esi_title_match"] = {
        "article": article_title,
        "esi": esi_title,
        "filename": saved_name,
    }
    document.meta_json = _dumps(meta)
    session.flush()
    return document


def record_esi_link(session: Session, document_id: int, url: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")
    hints = list(_loads(document.esi_hints_json, []))
    hints.append(
        {
            "kind": "url",
            "value": url,
            "snippet": "Добавлено пользователем",
            "manual": True,
        }
    )
    seen: set[str] = set()
    unique = []
    for h in hints:
        key = f"{h.get('kind')}:{str(h.get('value') or '').lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)
    document.esi_hints_json = _dumps(unique)
    meta = _loads(document.meta_json, {})
    meta["esi_attached_url"] = url
    document.meta_json = _dumps(meta)
    session.flush()
    return document


def remove_esi_link(session: Session, document_id: int, url: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")
    target = url.strip()
    hints = list(_loads(document.esi_hints_json, []))
    kept = [
        hint
        for hint in hints
        if not (
            isinstance(hint, dict)
            and hint.get("kind") == "url"
            and str(hint.get("value") or "").strip() == target
        )
    ]
    if len(kept) == len(hints):
        raise KeyError("Ссылка ESI не найдена")
    document.esi_hints_json = _dumps(kept)
    meta = _loads(document.meta_json, {})
    if str(meta.get("esi_attached_url") or "").strip() == target:
        meta.pop("esi_attached_url", None)
        document.meta_json = _dumps(meta)
    session.flush()
    return document


def detach_esi_file(
    session: Session,
    project: ProjectState,
    document_id: int,
    file_id: int,
) -> Document:
    document = _load_document(session, document_id)
    doc_file = next((f for f in document.files if f.id == file_id), None)
    if doc_file is None or doc_file.role != "esi":
        raise KeyError("Файл ESI не найден")
    relative_path = doc_file.relative_path
    filename = doc_file.filename
    _clear_parsed_content(session, document, only_doc_file_id=doc_file.id)
    session.delete(doc_file)
    session.flush()
    still_used = session.scalar(
        select(DocFile.id).where(DocFile.relative_path == relative_path).limit(1)
    )
    if still_used is None:
        path = _abs_from_rel(project, relative_path)
        if path.is_file():
            path.unlink()
    meta = _loads(document.meta_json, {})
    match = meta.get("esi_title_match")
    if isinstance(match, dict) and match.get("filename") == filename:
        meta.pop("esi_title_match", None)
        document.meta_json = _dumps(meta)
        session.flush()
    return document


def get_document_structure(session: Session, document_id: int) -> dict[str, Any]:
    session.expire_all()
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.files),
            selectinload(Document.sections).selectinload(Section.blocks),
            selectinload(Document.references),
        )
    )
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")

    sections_out = []
    for section in sorted(document.sections, key=lambda s: s.order_index):
        blocks_out = [
            {
                "id": block.id,
                "block_type": block.kind,
                "kind": block.kind,
                "text": block.text,
                "page": block.page,
                "bbox": _loads(block.bbox_json, None),
                "page_width": block.page_width,
                "page_height": block.page_height,
                "order_index": block.order_index,
                "meta": _loads(block.meta_json, {}),
            }
            for block in sorted(section.blocks, key=lambda b: b.order_index)
        ]
        sections_out.append(
            {
                "id": section.id,
                "section_type": section.section_type,
                "title": section.title or "",
                "page_start": section.page_start,
                "page_end": section.page_end,
                "useful_default": section.useful,
                "useful": section.useful,
                "order_index": section.order_index,
                "doc_file_id": section.doc_file_id,
                "blocks": blocks_out,
            }
        )

    return {
        "id": document.id,
        "title": document.title,
        "status": document.status,
        "doi": document.doi,
        "error_message": document.error_message,
        "esi_hints": _loads(document.esi_hints_json, []),
        "meta": _loads(document.meta_json, {}),
        "files": [
            {
                "id": f.id,
                "role": f.role,
                "relative_path": f.relative_path,
                "filename": f.filename,
                "page_count": f.page_count,
            }
            for f in document.files
        ],
        "sections": sections_out,
        "references": [
            {
                "id": r.id,
                "raw_text": r.raw_text,
                "doi": r.doi,
                "page": r.page,
                "order_index": r.order_index,
            }
            for r in sorted(document.references, key=lambda x: x.order_index)
        ],
    }


def serialize_document_brief(document: Document) -> dict[str, Any]:
    main = next((f for f in document.files if f.role == "main"), None)
    esi_count = sum(1 for f in document.files if f.role == "esi")
    golds = getattr(document, "gold_snapshots", None)
    return {
        "id": document.id,
        "title": document.title,
        "status": document.status,
        "doi": document.doi,
        "error_message": document.error_message,
        "source_stem": document.source_stem,
        "source_path": document.source_path,
        "main_file": None
        if main is None
        else {
            "id": main.id,
            "filename": main.filename,
            "relative_path": main.relative_path,
            "page_count": main.page_count,
        },
        "esi_files_count": esi_count,
        "esi_hints_count": len(_loads(document.esi_hints_json, [])),
        "sections_count": len(getattr(document, "sections", []) or []),
        "has_gold": bool(golds),
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


def resolve_pdf_path(
    project: ProjectState,
    session: Session,
    document_id: int,
    *,
    file_id: int | None = None,
    role: str = "main",
) -> Path:
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.files))
    )
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")
    if file_id is not None:
        df = next((f for f in document.files if f.id == file_id), None)
    else:
        df = next((f for f in document.files if f.role == role), None)
    if df is None:
        raise FileNotFoundError("PDF-файл не найден для документа")
    return _abs_from_rel(project, df.relative_path)
