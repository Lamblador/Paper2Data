"""Сравнение извлечённого графа с GoldSnapshot: precision/recall/F1, атрибуты, рёбра, цитаты."""

from __future__ import annotations

import math
import re
from typing import Any

# Допуск для числовых атрибутов (относительный)
DEFAULT_NUMERIC_TOLERANCE = 0.05

_UNIT_ALIASES: dict[str, str] = {
    "ms": "ms",
    "msec": "ms",
    "миллисекунд": "ms",
    "s": "s",
    "sec": "s",
    "секунд": "s",
    "ns": "ns",
    "нм": "nm",
    "nm": "nm",
    "nanometer": "nm",
    "nanometers": "nm",
    "cm-1": "cm^-1",
    "cm^-1": "cm^-1",
    "см-1": "cm^-1",
    "см⁻¹": "cm^-1",
    "k": "k",
    "kelvin": "k",
    "°c": "celsius",
    "c": "celsius",
    "celsius": "celsius",
    "%": "%",
    "percent": "%",
    "мкм": "um",
    "um": "um",
    "μm": "um",
}


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _norm_unit(unit: Any) -> str:
    raw = _norm_text(unit).replace(" ", "")
    return _UNIT_ALIASES.get(raw, raw)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    text = str(value).strip().replace(",", ".")
    # "1.2 ms" → 1.2
    m = re.match(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_unit_from_value(value: Any) -> str | None:
    if value is None or isinstance(value, (int, float)):
        return None
    text = str(value).strip()
    m = re.match(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*(.+)$", text)
    if m:
        u = m.group(1).strip()
        return u or None
    return None


def values_match(
    pred: Any,
    gold: Any,
    *,
    attr_type: str = "text",
    unit_pred: Any = None,
    unit_gold: Any = None,
    numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE,
) -> bool:
    """Сравнение значений атрибута с допуском по числам и нормализацией единиц."""
    if pred is None and gold is None:
        return True
    if pred is None or gold is None:
        return False

    t = (attr_type or "text").lower()
    if t in {"number", "number_with_unit", "range"} or (
        _to_float(pred) is not None and _to_float(gold) is not None
    ):
        fp = _to_float(pred)
        fg = _to_float(gold)
        if fp is None or fg is None:
            return _norm_text(pred) == _norm_text(gold)
        up = _norm_unit(unit_pred or _extract_unit_from_value(pred) or "")
        ug = _norm_unit(unit_gold or _extract_unit_from_value(gold) or "")
        if up and ug and up != ug:
            # без pint: разные единицы → несовпадение (конвертация — зона M6)
            return False
        if fg == 0:
            return abs(fp - fg) <= numeric_tolerance
        return abs(fp - fg) / abs(fg) <= numeric_tolerance

    if t == "bool":
        return bool(pred) == bool(gold)

    if t in {"smiles", "inchi"}:
        return _norm_text(pred).replace(" ", "") == _norm_text(gold).replace(" ", "")

    return _norm_text(pred) == _norm_text(gold)


def _node_key_attrs(node: dict[str, Any]) -> dict[str, Any]:
    attrs = dict(node.get("attributes") or {})
    # Часто полезные ключи для Compound
    keys = ("code", "formula", "name", "smiles", "iupac", "abbreviation")
    return {k: attrs.get(k) for k in keys if attrs.get(k) not in (None, "")}


def node_similarity(pred: dict[str, Any], gold: dict[str, Any]) -> float:
    """Оценка схожести 0..1 для greedy matching."""
    if (pred.get("entity_type") or "") != (gold.get("entity_type") or ""):
        return 0.0
    score = 0.0
    weight = 0.0

    pl = _norm_text(pred.get("label"))
    gl = _norm_text(gold.get("label"))
    if pl or gl:
        weight += 2.0
        if pl and gl and (pl == gl or pl in gl or gl in pl):
            score += 2.0
        elif pl and gl:
            # частичное совпадение токенов
            pt, gt = set(pl.split()), set(gl.split())
            if pt and gt:
                score += 2.0 * len(pt & gt) / len(pt | gt)

    pk = _node_key_attrs(pred)
    gk = _node_key_attrs(gold)
    for key in set(pk) | set(gk):
        weight += 1.5 if key in {"smiles", "formula", "code"} else 1.0
        if key in pk and key in gk and values_match(pk[key], gk[key], attr_type="text"):
            score += 1.5 if key in {"smiles", "formula", "code"} else 1.0

    if weight <= 0:
        return 0.5  # один тип, нет подписей — слабый матч
    return min(1.0, score / weight)


def match_nodes(
    predicted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    min_similarity: float = 0.45,
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    """Жадное взаимно-однозначное сопоставление узлов."""
    candidates: list[tuple[float, int, int]] = []
    for i, p in enumerate(predicted):
        for j, g in enumerate(gold):
            sim = node_similarity(p, g)
            if sim >= min_similarity:
                candidates.append((sim, i, j))
    candidates.sort(key=lambda x: x[0], reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for sim, i, j in candidates:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        pairs.append((predicted[i], gold[j], sim))
    return pairs


def _prf(tp: int, pred_n: int, gold_n: int) -> dict[str, float]:
    precision = (tp / pred_n) if pred_n else (1.0 if gold_n == 0 else 0.0)
    recall = (tp / gold_n) if gold_n else (1.0 if pred_n == 0 else 0.0)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": float(tp)}


def attribute_accuracy_for_pair(
    pred: dict[str, Any],
    gold: dict[str, Any],
    *,
    attr_types: dict[str, str] | None = None,
    numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE,
) -> tuple[int, int]:
    """Возвращает (совпало, всего сравниваемых ключей из эталона)."""
    g_attrs = dict(gold.get("attributes") or {})
    p_attrs = dict(pred.get("attributes") or {})
    if not g_attrs:
        return 0, 0
    ok = 0
    total = 0
    types = attr_types or {}
    for key, gval in g_attrs.items():
        if gval in (None, ""):
            continue
        total += 1
        pval = p_attrs.get(key)
        unit_p = p_attrs.get("unit") if key in {"value", "error"} else None
        unit_g = g_attrs.get("unit") if key in {"value", "error"} else None
        if values_match(
            pval,
            gval,
            attr_type=types.get(key, "text"),
            unit_pred=unit_p,
            unit_gold=unit_g,
            numeric_tolerance=numeric_tolerance,
        ):
            ok += 1
    return ok, total


def match_edges(
    pred_edges: list[dict[str, Any]],
    gold_edges: list[dict[str, Any]],
    node_id_map: dict[int, int],
) -> dict[str, float]:
    """Сопоставление рёбер после маппинга pred_node_id → gold_node_id."""
    gold_keys: list[tuple[str, int, int]] = []
    for e in gold_edges:
        gold_keys.append(
            (
                str(e.get("relation_type") or ""),
                int(e["source_node_id"]),
                int(e["target_node_id"]),
            )
        )
    gold_set = set(gold_keys)
    matched = 0
    for e in pred_edges:
        src = node_id_map.get(int(e["source_node_id"]))
        tgt = node_id_map.get(int(e["target_node_id"]))
        if src is None or tgt is None:
            continue
        key = (str(e.get("relation_type") or ""), src, tgt)
        if key in gold_set:
            matched += 1
            gold_set.discard(key)
    return _prf(matched, len(pred_edges), len(gold_edges))


def verified_quote_rate(nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> float:
    """Доля verified среди evidence с непустой цитатой."""
    total = 0
    verified = 0
    items = list(nodes) + list(edges or [])
    for item in items:
        for ev in item.get("evidences") or []:
            quote = (ev.get("quote") or "").strip()
            if not quote:
                continue
            total += 1
            if ev.get("verified"):
                verified += 1
    if total == 0:
        return 0.0
    return verified / total


def evaluate_graphs(
    predicted_nodes: list[dict[str, Any]],
    predicted_edges: list[dict[str, Any]],
    gold_nodes: list[dict[str, Any]],
    gold_edges: list[dict[str, Any]],
    *,
    attr_types: dict[str, str] | None = None,
    numeric_tolerance: float = DEFAULT_NUMERIC_TOLERANCE,
    min_similarity: float = 0.45,
) -> dict[str, Any]:
    """Полный набор метрик vs эталон."""
    # по типам
    types = sorted(
        {
            *(n.get("entity_type") or "Unknown" for n in predicted_nodes),
            *(n.get("entity_type") or "Unknown" for n in gold_nodes),
        }
    )
    by_type: dict[str, Any] = {}
    all_pairs: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for t in types:
        p = [n for n in predicted_nodes if (n.get("entity_type") or "Unknown") == t]
        g = [n for n in gold_nodes if (n.get("entity_type") or "Unknown") == t]
        pairs = match_nodes(p, g, min_similarity=min_similarity)
        all_pairs.extend(pairs)
        prf = _prf(len(pairs), len(p), len(g))
        by_type[t] = {
            **prf,
            "predicted": len(p),
            "gold": len(g),
            "matched": len(pairs),
        }

    overall = _prf(len(all_pairs), len(predicted_nodes), len(gold_nodes))

    matched_pred_ids = {int(p["id"]) for p, _, _ in all_pairs if p.get("id") is not None}
    matched_gold_ids = {int(g["id"]) for _, g, _ in all_pairs if g.get("id") is not None}
    missed_gold = [
        {
            "id": n.get("id"),
            "entity_type": n.get("entity_type"),
            "label": n.get("label"),
        }
        for n in gold_nodes
        if n.get("id") is None or int(n["id"]) not in matched_gold_ids
    ]
    extra_pred = [
        {
            "id": n.get("id"),
            "entity_type": n.get("entity_type"),
            "label": n.get("label"),
        }
        for n in predicted_nodes
        if n.get("id") is None or int(n["id"]) not in matched_pred_ids
    ]

    attr_ok = 0
    attr_total = 0
    for p, g, _ in all_pairs:
        ok, tot = attribute_accuracy_for_pair(
            p, g, attr_types=attr_types, numeric_tolerance=numeric_tolerance
        )
        attr_ok += ok
        attr_total += tot
    attr_acc = (attr_ok / attr_total) if attr_total else None

    node_id_map = {
        int(p["id"]): int(g["id"]) for p, g, _ in all_pairs if "id" in p and "id" in g
    }
    edge_metrics = match_edges(predicted_edges, gold_edges, node_id_map)
    vqr = verified_quote_rate(predicted_nodes, predicted_edges)

    return {
        "by_entity_type": by_type,
        "entities": {
            **overall,
            "predicted": len(predicted_nodes),
            "gold": len(gold_nodes),
            "matched": len(all_pairs),
        },
        "attribute_accuracy": attr_acc,
        "attribute_correct": attr_ok,
        "attribute_total": attr_total,
        "edges": {
            **edge_metrics,
            "predicted": len(predicted_edges),
            "gold": len(gold_edges),
        },
        "verified_quote_rate": vqr,
        "missed_gold": missed_gold,
        "extra_predicted": extra_pred,
        "matched_pairs": [
            {
                "pred_id": p.get("id"),
                "gold_id": g.get("id"),
                "entity_type": p.get("entity_type"),
                "similarity": round(sim, 4),
                "pred_label": p.get("label"),
                "gold_label": g.get("label"),
            }
            for p, g, sim in all_pairs
        ],
    }
