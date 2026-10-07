"""CRUD графа: узлы, рёбра, evidence, эталон, экспорт."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState
from paper2data.db.models import (
    Document,
    Edge,
    EntityType,
    Evidence,
    GoldSnapshot,
    Node,
    RelationType,
)
from paper2data.schema.service import get_active_schema_version

NODE_STATUSES = {"manual", "proposed", "accepted", "rejected"}


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _require_status(status: str) -> str:
    if status not in NODE_STATUSES:
        raise ValueError(f"Недопустимый статус: {status}")
    return status


def serialize_evidence(ev: Evidence) -> dict[str, Any]:
    return {
        "id": ev.id,
        "target_kind": ev.target_kind,
        "node_id": ev.node_id,
        "edge_id": ev.edge_id,
        "attribute_key": ev.attribute_key,
        "block_id": ev.block_id,
        "quote": ev.quote,
        "page": ev.page,
        "bbox": _loads(ev.bbox_json, None),
        "char_start": ev.char_start,
        "char_end": ev.char_end,
        "created_by": ev.created_by,
        "verified": ev.verified,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def serialize_node(node: Node) -> dict[str, Any]:
    et = node.entity_type
    return {
        "id": node.id,
        "document_id": node.document_id,
        "entity_type_id": node.entity_type_id,
        "entity_type": et.type_id if et else None,
        "entity_type_name": et.name if et else None,
        "label": node.label,
        "attributes": _loads(node.attributes_json, {}),
        "status": node.status,
        "canonical_id": node.canonical_id,
        "run_id": node.run_id,
        "pos_x": node.pos_x,
        "pos_y": node.pos_y,
        "evidences": [serialize_evidence(e) for e in (node.evidences or [])],
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def serialize_edge(edge: Edge) -> dict[str, Any]:
    rt = edge.relation_type
    return {
        "id": edge.id,
        "document_id": edge.document_id,
        "relation_type_id": edge.relation_type_id,
        "relation_type": rt.type_id if rt else None,
        "relation_type_name": rt.name if rt else None,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "attributes": _loads(edge.attributes_json, {}),
        "status": edge.status,
        "run_id": edge.run_id,
        "evidences": [serialize_evidence(e) for e in (edge.evidences or [])],
        "created_at": edge.created_at.isoformat() if edge.created_at else None,
        "updated_at": edge.updated_at.isoformat() if edge.updated_at else None,
    }


def get_document(session: Session, document_id: int) -> Document:
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"Документ не найден: {document_id}")
    return doc


def list_documents(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(Document).order_by(Document.id.desc())).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "doi": d.doi,
            "status": d.status,
            "source_path": d.source_path,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in rows
    ]


def create_document(
    session: Session,
    *,
    title: str,
    doi: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    doc = Document(
        title=title.strip() or "Без названия",
        doi=doi,
        source_path=source_path,
        source_stem=(Path(source_path).stem if source_path else title.strip() or "doc").lower(),
        status="new",
        esi_hints_json="[]",
        meta_json="{}",
    )
    session.add(doc)
    session.flush()
    return {
        "id": doc.id,
        "title": doc.title,
        "doi": doc.doi,
        "status": doc.status,
        "source_path": doc.source_path,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _resolve_entity_type(session: Session, type_key: str | int) -> EntityType:
    schema = get_active_schema_version(session)
    if schema is None:
        raise RuntimeError("Схема проекта не применена")
    if isinstance(type_key, int) or (isinstance(type_key, str) and type_key.isdigit()):
        et = session.get(EntityType, int(type_key))
        if et is None or et.schema_version_id != schema.id:
            raise LookupError("Тип сущности не найден в активной схеме")
        return et
    et = next((e for e in schema.entity_types if e.type_id == type_key), None)
    if et is None:
        raise LookupError(f"Тип сущности не найден: {type_key}")
    return et


def _resolve_relation_type(session: Session, type_key: str | int) -> RelationType:
    schema = get_active_schema_version(session)
    if schema is None:
        raise RuntimeError("Схема проекта не применена")
    if isinstance(type_key, int) or (isinstance(type_key, str) and str(type_key).isdigit()):
        rt = session.get(RelationType, int(type_key))
        if rt is None or rt.schema_version_id != schema.id:
            raise LookupError("Тип связи не найден в активной схеме")
        return rt
    rt = next((r for r in schema.relation_types if r.type_id == type_key), None)
    if rt is None:
        raise LookupError(f"Тип связи не найден: {type_key}")
    return rt


def _node_label(et: EntityType, attributes: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    if et.label_attribute and attributes.get(et.label_attribute) not in (None, ""):
        return str(attributes[et.label_attribute])
    return et.name


def get_node(session: Session, node_id: int) -> dict[str, Any]:
    node = session.scalars(
        select(Node)
        .where(Node.id == node_id)
        .options(selectinload(Node.entity_type), selectinload(Node.evidences))
    ).first()
    if node is None:
        raise LookupError(f"Узел не найден: {node_id}")
    return serialize_node(node)


def list_nodes(session: Session, document_id: int) -> list[dict[str, Any]]:
    get_document(session, document_id)
    stmt = (
        select(Node)
        .where(Node.document_id == document_id)
        .options(
            selectinload(Node.entity_type),
            selectinload(Node.evidences),
        )
        .order_by(Node.id)
    )
    return [serialize_node(n) for n in session.scalars(stmt).all()]


def create_node(session: Session, document_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    get_document(session, document_id)
    et = _resolve_entity_type(session, payload.get("entity_type") or payload.get("entity_type_id"))
    attributes = dict(payload.get("attributes") or {})
    status = _require_status(str(payload.get("status") or "manual"))
    node = Node(
        document_id=document_id,
        entity_type_id=et.id,
        label=_node_label(et, attributes, payload.get("label")),
        attributes_json=_dumps(attributes),
        status=status,
        canonical_id=payload.get("canonical_id"),
        run_id=int(payload["run_id"]) if payload.get("run_id") is not None else None,
        pos_x=float(payload.get("pos_x") or 0),
        pos_y=float(payload.get("pos_y") or 0),
    )
    session.add(node)
    session.flush()

    evidence = payload.get("evidence")
    if evidence:
        session.add(
            Evidence(
                target_kind="node",
                node_id=node.id,
                block_id=evidence.get("block_id"),
                quote=str(evidence.get("quote") or ""),
                page=evidence.get("page"),
                bbox_json=_dumps(evidence["bbox"]) if evidence.get("bbox") is not None else None,
                char_start=evidence.get("char_start"),
                char_end=evidence.get("char_end"),
                created_by=str(evidence.get("created_by") or "human"),
                verified=bool(evidence.get("verified", False)),
            )
        )
        session.flush()

    session.refresh(node)
    node = session.scalars(
        select(Node)
        .where(Node.id == node.id)
        .options(selectinload(Node.entity_type), selectinload(Node.evidences))
    ).one()
    return serialize_node(node)


def update_node(session: Session, node_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    node = session.get(Node, node_id)
    if node is None:
        raise LookupError(f"Узел не найден: {node_id}")
    if "attributes" in payload and payload["attributes"] is not None:
        attrs = dict(payload["attributes"])
        node.attributes_json = _dumps(attrs)
        if "label" not in payload:
            node.label = _node_label(node.entity_type, attrs, None)
    if "label" in payload and payload["label"] is not None:
        node.label = str(payload["label"])
    if "status" in payload and payload["status"] is not None:
        node.status = _require_status(str(payload["status"]))
    if "pos_x" in payload and payload["pos_x"] is not None:
        node.pos_x = float(payload["pos_x"])
    if "pos_y" in payload and payload["pos_y"] is not None:
        node.pos_y = float(payload["pos_y"])
    if "canonical_id" in payload:
        node.canonical_id = payload["canonical_id"]
    session.flush()
    node = session.scalars(
        select(Node)
        .where(Node.id == node.id)
        .options(selectinload(Node.entity_type), selectinload(Node.evidences))
    ).one()
    return serialize_node(node)


def delete_node(session: Session, node_id: int) -> None:
    node = session.get(Node, node_id)
    if node is None:
        raise LookupError(f"Узел не найден: {node_id}")
    # Рёбра удалятся по CASCADE
    session.delete(node)


def list_edges(session: Session, document_id: int) -> list[dict[str, Any]]:
    get_document(session, document_id)
    stmt = (
        select(Edge)
        .where(Edge.document_id == document_id)
        .options(
            selectinload(Edge.relation_type),
            selectinload(Edge.evidences),
        )
        .order_by(Edge.id)
    )
    return [serialize_edge(e) for e in session.scalars(stmt).all()]


def create_edge(session: Session, document_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    get_document(session, document_id)
    rt = _resolve_relation_type(
        session, payload.get("relation_type") or payload.get("relation_type_id")
    )
    source = session.get(Node, int(payload["source_node_id"]))
    target = session.get(Node, int(payload["target_node_id"]))
    if source is None or target is None:
        raise LookupError("Исходный или целевой узел не найден")
    if source.document_id != document_id or target.document_id != document_id:
        raise ValueError("Узлы должны принадлежать тому же документу")

    edge = Edge(
        document_id=document_id,
        relation_type_id=rt.id,
        source_node_id=source.id,
        target_node_id=target.id,
        attributes_json=_dumps(dict(payload.get("attributes") or {})),
        status=_require_status(str(payload.get("status") or "manual")),
        run_id=int(payload["run_id"]) if payload.get("run_id") is not None else None,
    )
    session.add(edge)
    session.flush()

    evidence = payload.get("evidence")
    if evidence:
        session.add(
            Evidence(
                target_kind="edge",
                edge_id=edge.id,
                block_id=evidence.get("block_id"),
                quote=str(evidence.get("quote") or ""),
                page=evidence.get("page"),
                bbox_json=_dumps(evidence["bbox"]) if evidence.get("bbox") is not None else None,
                char_start=evidence.get("char_start"),
                char_end=evidence.get("char_end"),
                created_by=str(evidence.get("created_by") or "human"),
                verified=bool(evidence.get("verified", False)),
            )
        )
        session.flush()

    edge = session.scalars(
        select(Edge)
        .where(Edge.id == edge.id)
        .options(selectinload(Edge.relation_type), selectinload(Edge.evidences))
    ).one()
    return serialize_edge(edge)


def update_edge(session: Session, edge_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    edge = session.get(Edge, edge_id)
    if edge is None:
        raise LookupError(f"Ребро не найдено: {edge_id}")
    if "attributes" in payload and payload["attributes"] is not None:
        edge.attributes_json = _dumps(dict(payload["attributes"]))
    if "status" in payload and payload["status"] is not None:
        edge.status = _require_status(str(payload["status"]))
    session.flush()
    edge = session.scalars(
        select(Edge)
        .where(Edge.id == edge.id)
        .options(selectinload(Edge.relation_type), selectinload(Edge.evidences))
    ).one()
    return serialize_edge(edge)


def delete_edge(session: Session, edge_id: int) -> None:
    edge = session.get(Edge, edge_id)
    if edge is None:
        raise LookupError(f"Ребро не найдено: {edge_id}")
    session.delete(edge)


def create_evidence(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("target_kind") or "node")
    if kind not in {"node", "edge", "attribute"}:
        raise ValueError("target_kind: node | edge | attribute")
    node_id = payload.get("node_id")
    edge_id = payload.get("edge_id")
    if kind in {"node", "attribute"} and not node_id:
        raise ValueError("Для node/attribute нужен node_id")
    if kind == "edge" and not edge_id:
        raise ValueError("Для edge нужен edge_id")

    ev = Evidence(
        target_kind=kind,
        node_id=int(node_id) if node_id is not None else None,
        edge_id=int(edge_id) if edge_id is not None else None,
        attribute_key=payload.get("attribute_key"),
        block_id=payload.get("block_id"),
        quote=str(payload.get("quote") or ""),
        page=payload.get("page"),
        bbox_json=_dumps(payload["bbox"]) if payload.get("bbox") is not None else None,
        char_start=payload.get("char_start"),
        char_end=payload.get("char_end"),
        created_by=str(payload.get("created_by") or "human"),
        verified=bool(payload.get("verified", False)),
    )
    session.add(ev)
    session.flush()
    return serialize_evidence(ev)


def delete_evidence(session: Session, evidence_id: int) -> None:
    ev = session.get(Evidence, evidence_id)
    if ev is None:
        raise LookupError(f"Evidence не найден: {evidence_id}")
    session.delete(ev)


def get_graph(session: Session, document_id: int) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "nodes": list_nodes(session, document_id),
        "edges": list_edges(session, document_id),
    }


def save_gold_snapshot(
    session: Session,
    document_id: int,
    *,
    label: str = "gold",
    only_accepted: bool = True,
) -> dict[str, Any]:
    doc = get_document(session, document_id)
    graph = get_graph(session, document_id)
    if only_accepted:
        nodes = [n for n in graph["nodes"] if n["status"] in {"accepted", "manual"}]
        node_ids = {n["id"] for n in nodes}
        edges = [
            e
            for e in graph["edges"]
            if e["status"] in {"accepted", "manual"}
            and e["source_node_id"] in node_ids
            and e["target_node_id"] in node_ids
        ]
    else:
        nodes = graph["nodes"]
        edges = graph["edges"]

    payload = {
        "document_id": document_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "nodes": nodes,
        "edges": edges,
    }
    snap = GoldSnapshot(
        document_id=document_id,
        label=label,
        payload_json=_dumps(payload),
        node_count=len(nodes),
        edge_count=len(edges),
    )
    session.add(snap)
    doc.status = "gold"
    session.flush()
    return {
        "id": snap.id,
        "document_id": document_id,
        "label": snap.label,
        "node_count": snap.node_count,
        "edge_count": snap.edge_count,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
        "payload": payload,
    }


def list_gold_snapshots(session: Session, document_id: int) -> list[dict[str, Any]]:
    get_document(session, document_id)
    rows = session.scalars(
        select(GoldSnapshot)
        .where(GoldSnapshot.document_id == document_id)
        .order_by(GoldSnapshot.id.desc())
    ).all()
    return [
        {
            "id": s.id,
            "document_id": s.document_id,
            "label": s.label,
            "node_count": s.node_count,
            "edge_count": s.edge_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]


def get_gold_snapshot(session: Session, snapshot_id: int) -> dict[str, Any]:
    snap = session.get(GoldSnapshot, snapshot_id)
    if snap is None:
        raise LookupError(f"Эталон не найден: {snapshot_id}")
    return {
        "id": snap.id,
        "document_id": snap.document_id,
        "label": snap.label,
        "node_count": snap.node_count,
        "edge_count": snap.edge_count,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
        "payload": _loads(snap.payload_json, {}),
    }


def export_document_graph(
    session: Session,
    project: ProjectState,
    document_id: int,
) -> dict[str, Any]:
    doc = get_document(session, document_id)
    graph = get_graph(session, document_id)
    exports = project.exports_dir
    exports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"doc{document_id}_{stamp}"

    json_path = exports / f"{base}_graph.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "document": {
                    "id": doc.id,
                    "title": doc.title,
                    "doi": doc.doi,
                    "status": doc.status,
                },
                "nodes": graph["nodes"],
                "edges": graph["edges"],
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph["nodes"]:
        by_type[str(node.get("entity_type") or "Unknown")].append(node)

    csv_files: list[str] = []
    for type_id, nodes in by_type.items():
        # Собираем все ключи атрибутов
        attr_keys: list[str] = []
        seen: set[str] = set()
        for n in nodes:
            for k in (n.get("attributes") or {}).keys():
                if k not in seen:
                    seen.add(k)
                    attr_keys.append(k)

        csv_name = f"{base}_{type_id}.csv"
        csv_path = exports / csv_name
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["node_id", "label", "status", "entity_type", *attr_keys]
            )
            for n in nodes:
                attrs = n.get("attributes") or {}
                writer.writerow(
                    [
                        n["id"],
                        n.get("label") or "",
                        n.get("status") or "",
                        type_id,
                        *[attrs.get(k, "") for k in attr_keys],
                    ]
                )
        csv_files.append(str(csv_path))

    return {
        "json_path": str(json_path),
        "csv_paths": csv_files,
        "exports_dir": str(exports),
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
    }
