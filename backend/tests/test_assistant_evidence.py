"""Ассистент создаёт узлы только с цитатой; очередь проверки видит run_id=null."""

from pathlib import Path

from paper2data.assistant.tools import apply_mutation, execute_tool
from paper2data.core.project import close_project, create_project
from paper2data.db.models import Block
from paper2data.db.session import dispose_db, session_scope
from paper2data.extraction.review import list_review_queue
from paper2data.graph import service as graph_service
from paper2data.schema import service as schema_service


def test_create_node_requires_quote_and_appears_in_review(tmp_path: Path):
    project = create_project(tmp_path / "proj", name="T")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Статья")
            doc_id = doc["id"]
            session.add(
                Block(
                    document_id=doc_id,
                    kind="paragraph",
                    text="Compound 1-Sm is [Sm(Btfa)3(bipy)].",
                    page=1,
                    order_index=0,
                )
            )
            session.flush()

            result, prop = execute_tool(
                session,
                document_id=doc_id,
                name="create_node",
                arguments={
                    "entity_type": "Compound",
                    "label": "1-Sm",
                    "attributes": {"code": "1-Sm"},
                },
            )
            assert result.get("ok") is False
            assert prop is None

            result, prop = execute_tool(
                session,
                document_id=doc_id,
                name="create_node",
                arguments={
                    "entity_type": "Compound",
                    "label": "1-Sm",
                    "quote": "Compound 1-Sm is [Sm(Btfa)3(bipy)].",
                    "block_id": 1,
                    "attributes": {"code": "1-Sm"},
                },
            )
            assert result.get("ok") is True
            assert prop is not None

            applied = apply_mutation(
                session,
                document_id=doc_id,
                project=None,
                action="create_node",
                args=prop["args"],
            )
            assert applied["ok"] is True
            node = applied["node"]
            assert node["status"] == "proposed"
            assert node["run_id"] is None
            assert node["evidences"]
            assert "1-Sm" in (node["evidences"][0].get("quote") or "")

            queue = list_review_queue(session, doc_id, run_id=999)
            assert queue["counts"]["total"] >= 1
            assert any(c["id"] == node["id"] for c in queue["cards"])
    finally:
        dispose_db()
        close_project()
