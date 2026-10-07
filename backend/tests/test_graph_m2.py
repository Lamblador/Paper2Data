"""Интеграционный тест применения схемы и CRUD графа."""

from __future__ import annotations

from pathlib import Path

from paper2data.core.project import create_project
from paper2data.db.session import dispose_db, session_scope
from paper2data.graph import service as graph_service
from paper2data.schema import service as schema_service


def test_apply_schema_and_graph_crud(tmp_path: Path):
    project = create_project(tmp_path / "proj", name="M2")
    try:
        with session_scope() as session:
            schema = schema_service.apply_template(
                session, project, "coordination_compounds"
            )
            assert schema["template_id"] == "coordination_compounds"
            assert any(e["id"] == "Compound" for e in schema["entity_types"])

            doc = graph_service.create_document(session, title="Тестовая статья")
            doc_id = doc["id"]

            node = graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Compound",
                    "attributes": {"code": "1", "formula": "Eu(DBM)3"},
                    "pos_x": 120,
                    "pos_y": 80,
                    "evidence": {"quote": "complex 1", "page": 2},
                },
            )
            assert node["label"] == "1"
            assert node["status"] == "manual"
            assert len(node["evidences"]) == 1

            prop = graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Property",
                    "attributes": {"property_type": "lifetime", "value": 1.2, "unit": "ms"},
                    "status": "accepted",
                    "pos_x": 300,
                    "pos_y": 80,
                },
            )
            edge = graph_service.create_edge(
                session,
                doc_id,
                {
                    "relation_type": "HAS_PROPERTY",
                    "source_node_id": node["id"],
                    "target_node_id": prop["id"],
                    "status": "accepted",
                },
            )
            assert edge["relation_type"] == "HAS_PROPERTY"

            gold = graph_service.save_gold_snapshot(session, doc_id)
            assert gold["node_count"] >= 2
            assert gold["edge_count"] >= 1

            exported = graph_service.export_document_graph(session, project, doc_id)
            assert Path(exported["json_path"]).is_file()
            assert exported["csv_paths"]
            assert all(Path(p).is_file() for p in exported["csv_paths"])
    finally:
        dispose_db()
