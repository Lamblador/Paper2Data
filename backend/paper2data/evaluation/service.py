"""Сервис оценки: сравнение с эталоном, сохранение Evaluation, лидерборд."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState
from paper2data.db.models import (
    Edge,
    EntityType,
    Evaluation,
    ExtractionRun,
    GoldSnapshot,
    Node,
)
from paper2data.evaluation.metrics import evaluate_graphs
from paper2data.graph import service as graph_service
from paper2data.llm import profiles as llm_profiles


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def serialize_evaluation(row: Evaluation) -> dict[str, Any]:
    run = row.extraction_run
    return {
        "id": row.id,
        "extraction_run_id": row.extraction_run_id,
        "gold_snapshot_id": row.gold_snapshot_id,
        "document_id": row.document_id,
        "precision": row.precision,
        "recall": row.recall,
        "f1": row.f1,
        "attribute_accuracy": row.attribute_accuracy,
        "edge_f1": row.edge_f1,
        "verified_quote_rate": row.verified_quote_rate,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "cost_usd": row.cost_usd,
        "metrics": _loads(row.metrics_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "run": {
            "id": run.id if run else None,
            "llm_profile_id": run.llm_profile_id if run else None,
            "recipe_id": run.recipe_id if run else None,
            "strategy": run.strategy if run else None,
            "status": run.status if run else None,
        }
        if run
        else None,
    }


def _nodes_for_run(session: Session, run: ExtractionRun) -> list[dict[str, Any]]:
    """Только узлы этого прогона. Пустой прогон → [] (не fallback на эталон)."""
    rows = session.scalars(
        select(Node)
        .where(Node.document_id == run.document_id, Node.run_id == run.id)
        .options(selectinload(Node.entity_type), selectinload(Node.evidences))
    ).all()
    return [graph_service.serialize_node(n) for n in rows]


def _edges_for_run(session: Session, run: ExtractionRun) -> list[dict[str, Any]]:
    """Только рёбра этого прогона. Пустой прогон → []."""
    rows = session.scalars(
        select(Edge)
        .where(Edge.document_id == run.document_id, Edge.run_id == run.id)
        .options(selectinload(Edge.relation_type), selectinload(Edge.evidences))
    ).all()
    return [graph_service.serialize_edge(e) for e in rows]


def _latest_gold(session: Session, document_id: int) -> GoldSnapshot | None:
    return session.scalars(
        select(GoldSnapshot)
        .where(GoldSnapshot.document_id == document_id)
        .order_by(GoldSnapshot.id.desc())
    ).first()


def evaluate_run(
    session: Session,
    project: ProjectState,
    *,
    run_id: int,
    gold_snapshot_id: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise LookupError(f"Прогон не найден: {run_id}")

    snap: GoldSnapshot | None
    if gold_snapshot_id is not None:
        snap = session.get(GoldSnapshot, gold_snapshot_id)
        if snap is None:
            raise LookupError(f"Эталон не найден: {gold_snapshot_id}")
    else:
        snap = _latest_gold(session, run.document_id)
        if snap is None:
            raise LookupError("Нет GoldSnapshot для документа — сохраните эталон")

    gold_payload = _loads(snap.payload_json, {})
    gold_nodes = list(gold_payload.get("nodes") or [])
    gold_edges = list(gold_payload.get("edges") or [])

    pred_nodes = _nodes_for_run(session, run)
    pred_edges = _edges_for_run(session, run)

    # типы атрибутов из схемы (по возможности)
    attr_types: dict[str, str] = {}
    for et in session.scalars(
        select(EntityType).options(selectinload(EntityType.attributes))
    ).all():
        for attr in et.attributes or []:
            attr_types[attr.attr_id] = attr.attr_type

    metrics = evaluate_graphs(
        pred_nodes,
        pred_edges,
        gold_nodes,
        gold_edges,
        attr_types=attr_types,
    )

    stats = _loads(run.stats_json, {})
    tokens_in = int(stats.get("prompt_tokens") or stats.get("tokens_in") or 0)
    tokens_out = int(stats.get("completion_tokens") or stats.get("tokens_out") or 0)

    cost = 0.0
    try:
        profile = llm_profiles.get_profile(run.llm_profile_id, project)
        from paper2data.evaluation.cost import cost_usd

        cost = cost_usd(
            tokens_in,
            tokens_out,
            price_in_per_1m=profile.price_in_per_1m,
            price_out_per_1m=profile.price_out_per_1m,
        )
    except KeyError:
        pass

    entities = metrics.get("entities") or {}
    edges = metrics.get("edges") or {}
    result = {
        "metrics": metrics,
        "precision": entities.get("precision"),
        "recall": entities.get("recall"),
        "f1": entities.get("f1"),
        "attribute_accuracy": metrics.get("attribute_accuracy"),
        "edge_f1": edges.get("f1"),
        "verified_quote_rate": metrics.get("verified_quote_rate"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "gold_snapshot_id": snap.id,
        "extraction_run_id": run.id,
        "document_id": run.document_id,
    }

    if persist:
        row = Evaluation(
            extraction_run_id=run.id,
            gold_snapshot_id=snap.id,
            document_id=run.document_id,
            metrics_json=_dumps(metrics),
            precision=result["precision"],
            recall=result["recall"],
            f1=result["f1"],
            attribute_accuracy=result["attribute_accuracy"],
            edge_f1=result["edge_f1"],
            verified_quote_rate=result["verified_quote_rate"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=result["cost_usd"],
        )
        session.add(row)
        session.flush()
        result["evaluation"] = serialize_evaluation(row)
        result["id"] = row.id
    return result


def list_evaluations(
    session: Session,
    *,
    document_id: int | None = None,
    llm_profile_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(Evaluation)
        .options(selectinload(Evaluation.extraction_run))
        .order_by(Evaluation.id.desc())
    )
    if document_id is not None:
        stmt = stmt.where(Evaluation.document_id == document_id)
    rows = session.scalars(stmt).all()
    out = [serialize_evaluation(r) for r in rows]
    if llm_profile_id:
        out = [
            e
            for e in out
            if e.get("run") and e["run"].get("llm_profile_id") == llm_profile_id
        ]
    return out


def leaderboard(session: Session, project: ProjectState) -> dict[str, Any]:
    """Агрегация по (llm_profile_id, strategy) на документах с эталоном."""
    rows = session.scalars(
        select(Evaluation)
        .options(selectinload(Evaluation.extraction_run))
        .order_by(Evaluation.id.desc())
    ).all()

    # последняя оценка на тройку (profile, strategy, document)
    best: dict[tuple[str, str, int], Evaluation] = {}
    for row in rows:
        run = row.extraction_run
        if run is None:
            continue
        strategy = str(run.strategy or "") or "default"
        key = (run.llm_profile_id, strategy, row.document_id)
        if key not in best:
            best[key] = row

    by_bucket: dict[tuple[str, str], dict[str, Any]] = {}
    for (profile_id, strategy, _doc_id), row in best.items():
        bkey = (profile_id, strategy)
        bucket = by_bucket.setdefault(
            bkey,
            {
                "llm_profile_id": profile_id,
                "strategy": strategy,
                "name": profile_id,
                "model": None,
                "n_docs": 0,
                "f1_sum": 0.0,
                "precision_sum": 0.0,
                "recall_sum": 0.0,
                "attr_sum": 0.0,
                "attr_n": 0,
                "edge_f1_sum": 0.0,
                "edge_n": 0,
                "vqr_sum": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "evaluations": [],
            },
        )
        bucket["n_docs"] += 1
        if row.f1 is not None:
            bucket["f1_sum"] += row.f1
        if row.precision is not None:
            bucket["precision_sum"] += row.precision
        if row.recall is not None:
            bucket["recall_sum"] += row.recall
        if row.attribute_accuracy is not None:
            bucket["attr_sum"] += row.attribute_accuracy
            bucket["attr_n"] += 1
        if row.edge_f1 is not None:
            bucket["edge_f1_sum"] += row.edge_f1
            bucket["edge_n"] += 1
        if row.verified_quote_rate is not None:
            bucket["vqr_sum"] += row.verified_quote_rate
        bucket["tokens_in"] += row.tokens_in
        bucket["tokens_out"] += row.tokens_out
        bucket["cost_usd"] += row.cost_usd
        bucket["evaluations"].append(serialize_evaluation(row))

    # имена из профилей
    name_map = {p.id: p for p in project.settings.llm_profiles}
    ranking: list[dict[str, Any]] = []
    for (pid, strategy), b in by_bucket.items():
        n = max(1, b["n_docs"])
        profile = name_map.get(pid)
        ranking.append(
            {
                "llm_profile_id": pid,
                "strategy": strategy,
                "name": profile.name if profile else pid,
                "model": profile.model if profile else None,
                "n_docs": b["n_docs"],
                "avg_f1": round(b["f1_sum"] / n, 4),
                "avg_precision": round(b["precision_sum"] / n, 4),
                "avg_recall": round(b["recall_sum"] / n, 4),
                "avg_attribute_accuracy": (
                    round(b["attr_sum"] / b["attr_n"], 4) if b["attr_n"] else None
                ),
                "avg_edge_f1": (
                    round(b["edge_f1_sum"] / b["edge_n"], 4) if b["edge_n"] else None
                ),
                "avg_verified_quote_rate": round(b["vqr_sum"] / n, 4),
                "tokens_in": b["tokens_in"],
                "tokens_out": b["tokens_out"],
                "cost_usd": round(b["cost_usd"], 6),
                "evaluations": b["evaluations"],
            }
        )
    ranking.sort(key=lambda r: (r["avg_f1"], -r["cost_usd"]), reverse=True)
    return {"leaderboard": ranking, "count": len(ranking)}
