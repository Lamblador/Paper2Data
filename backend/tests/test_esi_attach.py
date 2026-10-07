"""Прикрепление ESI: сверка названия, ссылка и удаление файла."""

from __future__ import annotations

import json

import pymupdf as fitz
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from paper2data.core.project import create_project
from paper2data.db.models import Document
from paper2data.db.session import dispose_db, session_scope
from paper2data.ingest.esi import EsiTitleMismatch, titles_match
from paper2data.ingest.parser import extract_pdf_title_bytes
from paper2data.ingest.service import (
    _merge_esi_hints,
    attach_esi_file,
    detach_esi_file,
    record_esi_link,
    remove_esi_link,
    upload_pdf,
)

ARTICLE = (
    "Slow magnetic relaxation and luminescence properties in b-diketonate "
    "lanthanide(III) complexes. Preparation of Eu(III) and Yb(III) OLED devices†"
)
ESI = (
    "Slow magnetic relaxation and luminescence properties in β- "
    "diketonate lanthanide(III) complexes. Preparation of Eu(III) "
    "and Yb(III) OLED devices."
)


def _pdf_bytes(lines: list[tuple[str, float]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 80.0
    for text, size in lines:
        page.insert_text((72, y), text, fontsize=size)
        y += size + 8
    data = doc.tobytes()
    doc.close()
    return data


def test_titles_match_beta_and_dagger():
    assert titles_match(ARTICLE, ESI)
    assert not titles_match(
        ARTICLE,
        "Unrelated study of cobalt catalysts for water oxidation in alkaline media",
    )


def test_extract_title_joins_largest_font_lines():
    data = _pdf_bytes(
        [
            ("Slow magnetic relaxation and luminescence properties in β-", 18),
            ("diketonate lanthanide(III) complexes. Preparation of Eu(III)", 18),
            ("and Yb(III) OLED devices.", 18),
            ("Author One, Author Two", 11),
        ]
    )
    title = extract_pdf_title_bytes(data)
    assert titles_match(ARTICLE, title)


def test_merge_esi_hints_keeps_manual_link():
    merged = _merge_esi_hints(
        [{"kind": "phrase", "value": "ESI", "snippet": "из текста"}],
        [
            {
                "kind": "url",
                "value": "https://example.com/suppl/esi.pdf",
                "manual": True,
                "snippet": "Добавлено пользователем",
            }
        ],
    )
    assert any(hint.get("manual") and hint.get("kind") == "url" for hint in merged)
    assert any(hint.get("kind") == "phrase" for hint in merged)


def test_attach_requires_matching_title_and_supports_delete(tmp_path):
    project = create_project(tmp_path / "proj", name="ESI")
    main = _pdf_bytes(
        [
            ("Slow magnetic relaxation and luminescence", 16),
            ("properties in b-diketonate lanthanide(III)", 16),
            ("complexes. Preparation of Eu(III) and Yb(III)", 16),
            ("OLED devices", 16),
            ("A. Author", 10),
        ]
    )
    esi = _pdf_bytes(
        [
            ("Slow magnetic relaxation and luminescence properties in β-", 18),
            ("diketonate lanthanide(III) complexes. Preparation of Eu(III)", 18),
            ("and Yb(III) OLED devices.", 18),
        ]
    )
    other = _pdf_bytes(
        [("Unrelated study of cobalt catalysts for water oxidation", 16)]
    )
    try:
        with session_scope() as session:
            doc = upload_pdf(session, project, "paper.pdf", main)
            doc_id = doc.id

        with session_scope() as session:
            attached = attach_esi_file(
                session, project, doc_id, "esi.pdf", esi, ingest=False
            )
            assert any(f.role == "esi" for f in attached.files)
            meta = json.loads(attached.meta_json)
            assert titles_match(meta["esi_title_match"]["article"], meta["esi_title_match"]["esi"])

        with session_scope() as session:
            with pytest.raises(EsiTitleMismatch):
                attach_esi_file(
                    session, project, doc_id, "wrong.pdf", other, ingest=False
                )
        assert not (project.papers_dir / "wrong.pdf").exists()

        link = "https://pubs.rsc.org/tc/article-supplement/877406/pdf/d4tc00902a1_suppl/"
        with session_scope() as session:
            record_esi_link(session, doc_id, link)
        with session_scope() as session:
            remove_esi_link(session, doc_id, link)
            stored = session.get(Document, doc_id)
            assert stored is not None
            hints = json.loads(stored.esi_hints_json)
            assert all(hint.get("value") != link for hint in hints)

        with session_scope() as session:
            stored = session.scalar(
                select(Document)
                .where(Document.id == doc_id)
                .options(selectinload(Document.files))
            )
            assert stored is not None
            esi_file = next(f for f in stored.files if f.role == "esi")
            file_id = esi_file.id
            relative = esi_file.relative_path

        with session_scope() as session:
            detach_esi_file(session, project, doc_id, file_id)
        assert not (project.papers_dir / relative).exists()
        assert (project.papers_dir / "paper.pdf").is_file()
    finally:
        dispose_db()
