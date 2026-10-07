"""Очередь проверки предложений LLM: accept / edit / reject + дубли."""

from __future__ import annotations

import json
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState
from paper2data.db.models import Edge, Evidence, ExtractionRun, Node
from paper2data.extraction import engine as extraction_engine
from paper2data.graph import service as graph_service


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def list_review_queue(
    session: Session,
    document_id: int,
    *,
    run_id: int | None = None,
    status: str = "proposed",
    project: ProjectState | None = None,
) -> dict[str, Any]:
    graph_service.get_document(session, document_id)
    status_filter = (status or "proposed").strip().lower()
    if status_filter not in {"proposed", "accepted", "rejected", "all"}:
        raise ValueError("status: proposed | accepted | rejected | all")

    all_nodes = [
        graph_service.serialize_node(n)
        for n in session.scalars(
            select(Node)
            .where(Node.document_id == document_id)
            .options(selectinload(Node.entity_type), selectinload(Node.evidences))
            .order_by(Node.id)
        ).all()
    ]
    all_edges = [
        graph_service.serialize_edge(e)
        for e in session.scalars(
            select(Edge)
            .where(Edge.document_id == document_id)
            .options(selectinload(Edge.relation_type), selectinload(Edge.evidences))
            .order_by(Edge.id)
        ).all()
    ]
    status_counts = {
        "proposed": 0,
        "accepted": 0,
        "rejected": 0,
        "manual": 0,
        "other": 0,
        "no_evidence": 0,
    }
    for item in all_nodes + all_edges:
        st = str(item.get("status") or "other")
        if st in status_counts:
            status_counts[st] += 1
        else:
            status_counts["other"] += 1
        if st in {"proposed", "accepted", "manual"} and not (item.get("evidences") or []):
            status_counts["no_evidence"] += 1

    if status_filter == "all":
        nodes = [n for n in all_nodes if n.get("status") in {"proposed", "accepted", "rejected"}]
        edges = [e for e in all_edges if e.get("status") in {"proposed", "accepted", "rejected"}]
    else:
        nodes = [n for n in all_nodes if n.get("status") == status_filter]
        edges = [e for e in all_edges if e.get("status") == status_filter]

    nodes_by_id = {int(n["id"]): n for n in all_nodes if n.get("id") is not None}

    cards: list[dict[str, Any]] = []
    for n in nodes:
        ev = (n.get("evidences") or [{}])[0] if n.get("evidences") else {}
        cards.append(
            {
                "kind": "node",
                "id": n["id"],
                "run_id": n.get("run_id"),
                "label": n.get("label"),
                "type": n.get("entity_type"),
                "type_name": n.get("entity_type_name"),
                "attributes": n.get("attributes") or {},
                "status": n.get("status"),
                "quote": ev.get("quote") or "",
                "verified": bool(ev.get("verified")),
                "block_id": ev.get("block_id"),
                "page": ev.get("page"),
                "bbox": ev.get("bbox"),
                "evidence_id": ev.get("id"),
                "payload": n,
            }
        )
    for e in edges:
        ev = (e.get("evidences") or [{}])[0] if e.get("evidences") else {}
        src = nodes_by_id.get(int(e["source_node_id"])) if e.get("source_node_id") is not None else None
        tgt = nodes_by_id.get(int(e["target_node_id"])) if e.get("target_node_id") is not None else None
        src_label = (src or {}).get("label") or f"#{e.get('source_node_id')}"
        tgt_label = (tgt or {}).get("label") or f"#{e.get('target_node_id')}"
        src_type = (src or {}).get("entity_type_name") or (src or {}).get("entity_type")
        tgt_type = (tgt or {}).get("entity_type_name") or (tgt or {}).get("entity_type")
        rel_name = e.get("relation_type_name") or e.get("relation_type") or "связь"
        cards.append(
            {
                "kind": "edge",
                "id": e["id"],
                "run_id": e.get("run_id"),
                "label": f"{src_label} —[{rel_name}]→ {tgt_label}",
                "type": e.get("relation_type"),
                "type_name": rel_name,
                "attributes": e.get("attributes") or {},
                "status": e.get("status"),
                "source_node_id": e.get("source_node_id"),
                "target_node_id": e.get("target_node_id"),
                "source_label": src_label,
                "target_label": tgt_label,
                "source_type": src_type,
                "target_type": tgt_type,
                "source_status": (src or {}).get("status"),
                "target_status": (tgt or {}).get("status"),
                "quote": ev.get("quote") or "",
                "verified": bool(ev.get("verified")),
                "block_id": ev.get("block_id"),
                "page": ev.get("page"),
                "bbox": ev.get("bbox"),
                "evidence_id": ev.get("id"),
                "payload": e,
            }
        )

    # Предпочтительный прогон сверху, затем без run_id, затем остальные
    if run_id is not None:
        cards.sort(
            key=lambda c: (
                0
                if c.get("run_id") == run_id
                else (1 if c.get("run_id") is None else 2),
                c.get("id") or 0,
            )
        )

    duplicates = suggest_duplicate_merges(session, document_id)
    abbreviation_map: list[dict[str, Any]] = []
    run_status: str | None = None
    current_step_id: str | None = None
    resolved_run_id = run_id
    run_row: ExtractionRun | None = None
    if resolved_run_id is None and cards:
        for item in cards:
            if item.get("run_id") is not None:
                resolved_run_id = int(item["run_id"])
                break
    if resolved_run_id is not None:
        run_row = session.get(ExtractionRun, resolved_run_id)
        if run_row is not None:
            abbreviation_map = _loads(run_row.abbreviation_map_json, [])
            run_status = run_row.status
            current_step_id = run_row.current_step_id
    elif run_id is None:
        # последний прогон документа — для словаря обозначений
        run_row = session.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.document_id == document_id)
            .order_by(ExtractionRun.id.desc())
        ).first()
        if run_row is not None:
            resolved_run_id = run_row.id
            abbreviation_map = _loads(run_row.abbreviation_map_json, [])
            run_status = run_row.status
            current_step_id = run_row.current_step_id

    pipeline: list[str] = []
    steps_total = 0
    step_index = 0
    steps_history: list[dict[str, Any]] = []
    if run_row is not None:
        enriched = extraction_engine.serialize_run(run_row, session, project)
        pipeline = list(enriched["pipeline"])
        steps_total = int(enriched["steps_total"])
        step_index = int(enriched["step_index"])
        steps_history = list(enriched["steps_history"])

    return {
        "document_id": document_id,
        "run_id": resolved_run_id,
        "run_status": run_status,
        "current_step_id": current_step_id,
        "pipeline": pipeline,
        "steps_total": steps_total,
        "step_index": step_index,
        "steps_history": steps_history,
        "status_filter": status_filter,
        "abbreviation_map": abbreviation_map,
        "cards": cards,
        "duplicates": duplicates,
        "counts": {"nodes": len(nodes), "edges": len(edges), "total": len(cards)},
        "status_counts": status_counts,
    }


def reopen_item(
    session: Session,
    *,
    kind: str,
    item_id: int,
) -> dict[str, Any]:
    """Вернуть принятый/отклонённый элемент в очередь (status=proposed)."""
    import time

    from sqlalchemy.exc import OperationalError

    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            if kind == "node":
                return graph_service.update_node(session, item_id, {"status": "proposed"})
            if kind == "edge":
                return graph_service.update_edge(session, item_id, {"status": "proposed"})
            raise ValueError("kind: node | edge")
        except OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower() or attempt >= 4:
                raise
            session.rollback()
            time.sleep(0.4 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def accept_item(
    session: Session,
    *,
    kind: str,
    item_id: int,
) -> dict[str, Any]:
    if kind == "node":
        return graph_service.update_node(session, item_id, {"status": "accepted"})
    if kind == "edge":
        return graph_service.update_edge(session, item_id, {"status": "accepted"})
    raise ValueError("kind: node | edge")


def reject_item(
    session: Session,
    *,
    kind: str,
    item_id: int,
) -> dict[str, Any]:
    if kind == "node":
        return graph_service.update_node(session, item_id, {"status": "rejected"})
    if kind == "edge":
        return graph_service.update_edge(session, item_id, {"status": "rejected"})
    raise ValueError("kind: node | edge")


def edit_item(
    session: Session,
    *,
    kind: str,
    item_id: int,
    payload: dict[str, Any],
    accept: bool = True,
) -> dict[str, Any]:
    body = dict(payload)
    if accept:
        body["status"] = "accepted"
    if kind == "node":
        return graph_service.update_node(session, item_id, body)
    if kind == "edge":
        # только attributes/status для ребра
        return graph_service.update_edge(
            session,
            item_id,
            {
                k: body[k]
                for k in ("attributes", "status")
                if k in body
            },
        )
    raise ValueError("kind: node | edge")


def suggest_duplicate_merges(
    session: Session,
    document_id: int,
    *,
    threshold: float = 88.0,
) -> list[dict[str, Any]]:
    """Пары узлов одного типа с похожими label (proposed vs accepted/manual/proposed)."""
    nodes = session.scalars(
        select(Node)
        .where(
            Node.document_id == document_id,
            Node.status.in_(["proposed", "accepted", "manual"]),
        )
        .options(selectinload(Node.entity_type))
    ).all()
    suggestions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if a.entity_type_id != b.entity_type_id:
                continue
            la = (a.label or "").strip()
            lb = (b.label or "").strip()
            if not la or not lb:
                # сравним JSON атрибутов label_attribute
                continue
            score = float(fuzz.token_sort_ratio(la.lower(), lb.lower()))
            if score < threshold:
                continue
            pair = (min(a.id, b.id), max(a.id, b.id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            suggestions.append(
                {
                    "keep_id": a.id if a.status != "proposed" else b.id,
                    "merge_id": b.id if a.status != "proposed" else a.id,
                    "score": score,
                    "label_a": la,
                    "label_b": lb,
                    "entity_type": a.entity_type.type_id if a.entity_type else None,
                    "reason": "Похожие подписи одного типа сущности",
                }
            )
    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions[:50]


def merge_nodes(
    session: Session,
    *,
    keep_id: int,
    merge_id: int,
) -> dict[str, Any]:
    """Сливает merge → keep: переносит рёбра и evidence, удаляет merge."""
    keep = session.get(Node, keep_id)
    merge = session.get(Node, merge_id)
    if keep is None or merge is None:
        raise LookupError("Узел для слияния не найден")
    if keep.document_id != merge.document_id:
        raise ValueError("Узлы должны быть из одного документа")
    if keep.id == merge.id:
        raise ValueError("Нельзя слить узел сам с собой")

    # Атрибуты: keep имеет приоритет, пустые дополняем из merge
    keep_attrs = _loads(keep.attributes_json, {})
    merge_attrs = _loads(merge.attributes_json, {})
    for k, v in merge_attrs.items():
        if keep_attrs.get(k) in (None, "", [], {}):
            keep_attrs[k] = v
    keep.attributes_json = json.dumps(keep_attrs, ensure_ascii=False)
    if keep.status == "proposed":
        keep.status = "accepted"

    # Перенос рёбер
    edges = session.scalars(
        select(Edge).where(
            (Edge.source_node_id == merge.id) | (Edge.target_node_id == merge.id)
        )
    ).all()
    for edge in edges:
        if edge.source_node_id == merge.id:
            edge.source_node_id = keep.id
        if edge.target_node_id == merge.id:
            edge.target_node_id = keep.id
        # удалить петли / точные дубли
        if edge.source_node_id == edge.target_node_id:
            session.delete(edge)
            continue
        dup = session.scalars(
            select(Edge).where(
                Edge.document_id == edge.document_id,
                Edge.relation_type_id == edge.relation_type_id,
                Edge.source_node_id == edge.source_node_id,
                Edge.target_node_id == edge.target_node_id,
                Edge.id != edge.id,
            )
        ).first()
        if dup is not None:
            session.delete(edge)

    # Перенос evidence
    for ev in session.scalars(select(Evidence).where(Evidence.node_id == merge.id)).all():
        ev.node_id = keep.id

    session.delete(merge)
    session.flush()
    keep = session.scalars(
        select(Node)
        .where(Node.id == keep.id)
        .options(selectinload(Node.entity_type), selectinload(Node.evidences))
    ).one()
    return graph_service.serialize_node(keep)
