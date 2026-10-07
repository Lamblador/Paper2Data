"""Кросс-документные дубли Compounds → предложения canonical_id."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.db.models import EntityType, Node
from paper2data.graph import service as graph_service


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _smiles_key(s: Any) -> str:
    return _norm(s).replace(" ", "")


def _formula_key(s: Any) -> str:
    return re.sub(r"\s+", "", _norm(s))


def _attrs(node: Node) -> dict[str, Any]:
    try:
        import json

        return json.loads(node.attributes_json or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _match_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, str]:
    """Возвращает (score, reason)."""
    sa, sb = _smiles_key(a.get("smiles")), _smiles_key(b.get("smiles"))
    if sa and sb and sa == sb:
        return 1.0, "одинаковый SMILES"
    fa, fb = _formula_key(a.get("formula")), _formula_key(b.get("formula"))
    na, nb = _norm(a.get("name") or a.get("label")), _norm(b.get("name") or b.get("label"))
    if fa and fb and fa == fb and na and nb and na == nb:
        return 0.95, "формула + название"
    if fa and fb and fa == fb:
        return 0.8, "одинаковая формула"
    if na and nb and na == nb and len(na) >= 3:
        return 0.75, "одинаковое название"
    code_a, code_b = _norm(a.get("code")), _norm(b.get("code"))
    if code_a and code_b and code_a == code_b and fa and fb and fa == fb:
        return 0.85, "шифр + формула"
    return 0.0, ""


def _canonical_from_group(nodes: list[Node]) -> str:
    """Стабильный canonical_id для группы."""
    for n in nodes:
        if n.canonical_id:
            return n.canonical_id
    # хеш от лучшего ключа
    keys = []
    for n in nodes:
        attrs = _attrs(n)
        smi = _smiles_key(attrs.get("smiles"))
        if smi:
            keys.append(f"smiles:{smi}")
            break
        form = _formula_key(attrs.get("formula"))
        name = _norm(attrs.get("name") or n.label)
        if form:
            keys.append(f"formula:{form}|name:{name}")
            break
        if name:
            keys.append(f"name:{name}")
    seed = keys[0] if keys else f"nodes:{','.join(str(n.id) for n in sorted(nodes, key=lambda x: x.id))}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"cmp-{digest}"


def suggest_cross_document_duplicates(
    session: Session,
    *,
    entity_type: str = "Compound",
    min_score: float = 0.75,
) -> list[dict[str, Any]]:
    """Группы узлов одного типа из разных документов с совпадением name/formula/SMILES."""
    et = session.scalars(
        select(EntityType).where(EntityType.type_id == entity_type)
    ).first()
    if et is None:
        # поиск без учёта регистра / частичного
        ets = session.scalars(select(EntityType)).all()
        et = next((e for e in ets if e.type_id.lower() == entity_type.lower()), None)
    if et is None:
        return []

    nodes = session.scalars(
        select(Node)
        .where(
            Node.entity_type_id == et.id,
            Node.status.in_(["accepted", "manual", "proposed"]),
        )
        .options(selectinload(Node.entity_type))
    ).all()

    # Union-Find по парам
    parent: dict[int, int] = {n.id: n.id for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    node_by_id = {n.id: n for n in nodes}
    pair_reasons: dict[tuple[int, int], tuple[float, str]] = {}

    for i, a in enumerate(nodes):
        aa = {**_attrs(a), "label": a.label}
        for b in nodes[i + 1 :]:
            if a.document_id == b.document_id:
                continue
            bb = {**_attrs(b), "label": b.label}
            score, reason = _match_score(aa, bb)
            if score < min_score:
                continue
            union(a.id, b.id)
            pair_reasons[(min(a.id, b.id), max(a.id, b.id))] = (score, reason)

    groups: dict[int, list[Node]] = {}
    for n in nodes:
        groups.setdefault(find(n.id), []).append(n)

    suggestions: list[dict[str, Any]] = []
    for members in groups.values():
        docs = {m.document_id for m in members}
        if len(docs) < 2:
            continue
        suggested = _canonical_from_group(members)
        # max score among pairs in group
        max_score = 0.0
        reasons: list[str] = []
        ids = sorted(m.id for m in members)
        for i, x in enumerate(ids):
            for y in ids[i + 1 :]:
                pr = pair_reasons.get((x, y))
                if pr:
                    max_score = max(max_score, pr[0])
                    if pr[1] not in reasons:
                        reasons.append(pr[1])
        suggestions.append(
            {
                "entity_type": entity_type,
                "suggested_canonical_id": suggested,
                "score": max_score,
                "reasons": reasons,
                "nodes": [
                    {
                        "id": m.id,
                        "document_id": m.document_id,
                        "label": m.label,
                        "canonical_id": m.canonical_id,
                        "attributes": _attrs(m),
                        "status": m.status,
                    }
                    for m in members
                ],
            }
        )
    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions


def apply_canonical_ids(
    session: Session,
    *,
    node_ids: list[int],
    canonical_id: str,
) -> list[dict[str, Any]]:
    """Проставляет canonical_id выбранным узлам."""
    updated: list[dict[str, Any]] = []
    for nid in node_ids:
        node = session.get(Node, nid)
        if node is None:
            continue
        node.canonical_id = canonical_id
        session.flush()
        updated.append(graph_service.serialize_node(node))
    return updated
