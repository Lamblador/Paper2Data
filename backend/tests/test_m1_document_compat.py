"""Совместимость create_document M2 с полями M1."""

from paper2data.core.project import create_project
from paper2data.db.session import dispose_db, session_scope
from paper2data.graph.service import create_document


def test_create_document_sets_defaults(tmp_path):
    create_project(tmp_path / "proj", name="T")
    with session_scope() as session:
        doc = create_document(session, title="X", source_path="papers/a.pdf")
        assert doc["status"] == "new"
        assert doc["source_path"] == "papers/a.pdf"
    dispose_db()
