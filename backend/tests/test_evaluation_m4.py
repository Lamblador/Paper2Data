"""Тесты метрик matching и расчёта стоимости (M4)."""

from __future__ import annotations

from paper2data.evaluation.cost import (
    average_output_tokens_from_runs,
    cost_usd,
    count_tokens,
    estimate_batch_cost,
)
from paper2data.evaluation.metrics import (
    evaluate_graphs,
    match_edges,
    match_nodes,
    values_match,
    verified_quote_rate,
)


def test_values_match_numeric_tolerance_and_units():
    assert values_match(1.0, 1.04, attr_type="number", numeric_tolerance=0.05)
    assert not values_match(1.0, 1.2, attr_type="number", numeric_tolerance=0.05)
    assert values_match("1.2 ms", "1.2", attr_type="number_with_unit", unit_gold="ms")
    assert not values_match(
        1.2,
        1.2,
        attr_type="number_with_unit",
        unit_pred="ms",
        unit_gold="s",
    )
    assert values_match("CCO", "cco", attr_type="smiles")


def test_match_nodes_by_label_and_formula():
    gold = [
        {
            "id": 1,
            "entity_type": "Compound",
            "label": "1",
            "attributes": {"formula": "Eu(DBM)3BPhen", "name": "complex 1"},
        },
        {
            "id": 2,
            "entity_type": "Property",
            "label": "lifetime",
            "attributes": {"value": 1.2, "unit": "ms"},
        },
    ]
    pred = [
        {
            "id": 10,
            "entity_type": "Compound",
            "label": "1",
            "attributes": {"formula": "Eu(DBM)3BPhen"},
        },
        {
            "id": 11,
            "entity_type": "Compound",
            "label": "extra",
            "attributes": {"formula": "Gd(DBM)3"},
        },
        {
            "id": 12,
            "entity_type": "Property",
            "label": "lifetime",
            "attributes": {"value": 1.21, "unit": "ms"},
        },
    ]
    pairs = match_nodes(pred, gold, min_similarity=0.45)
    assert len(pairs) == 2
    metrics = evaluate_graphs(pred, [], gold, [], attr_types={"value": "number_with_unit"})
    assert metrics["entities"]["matched"] == 2
    assert metrics["entities"]["precision"] == 2 / 3
    assert metrics["entities"]["recall"] == 1.0
    assert metrics["attribute_accuracy"] is not None
    assert metrics["attribute_accuracy"] >= 0.5
    assert "Compound" in metrics["by_entity_type"]
    assert metrics["by_entity_type"]["Compound"]["tp"] == 1.0


def test_edge_match_and_verified_quotes():
    gold_edges = [
        {"id": 1, "relation_type": "HAS_PROPERTY", "source_node_id": 1, "target_node_id": 2}
    ]
    pred_edges = [
        {"id": 9, "relation_type": "HAS_PROPERTY", "source_node_id": 10, "target_node_id": 12},
        {"id": 8, "relation_type": "HAS_COMPONENT", "source_node_id": 10, "target_node_id": 99},
    ]
    node_map = {10: 1, 12: 2}
    em = match_edges(pred_edges, gold_edges, node_map)
    assert em["tp"] == 1.0
    assert em["precision"] == 0.5
    assert em["recall"] == 1.0

    nodes = [
        {
            "evidences": [
                {"quote": "abc", "verified": True},
                {"quote": "def", "verified": False},
                {"quote": "", "verified": False},
            ]
        }
    ]
    assert verified_quote_rate(nodes) == 0.5


def test_cost_usd_and_batch_estimate_math():
    # 1M in @ $1, 0.5M out @ $2 → $1 + $1 = $2
    assert abs(cost_usd(1_000_000, 500_000, price_in_per_1m=1.0, price_out_per_1m=2.0) - 2.0) < 1e-9
    assert cost_usd(0, 0, price_in_per_1m=5, price_out_per_1m=15) == 0.0

    avg = average_output_tokens_from_runs(
        [
            {"completion_tokens": 100},
            {"completion_tokens": 300},
            {"tokens": {"completion_tokens": 200}},  # ignored path without flat key
        ]
    )
    assert avg == 200.0

    estimate = estimate_batch_cost(
        document_ids=[1, 2],
        profiles=[
            {
                "id": "p1",
                "name": "cheap",
                "price_in_per_1m": 1.0,
                "price_out_per_1m": 2.0,
            },
            {
                "id": "p2",
                "name": "pricey",
                "price_in_per_1m": 10.0,
                "price_out_per_1m": 30.0,
            },
        ],
        steps_per_document=2,
        prompt_tokens_by_doc={1: 1000, 2: 3000},
        avg_output_tokens_per_run=500.0,
    )
    # in=4000 per model; out=500*2=1000 per model
    assert estimate["by_model"][0]["tokens_in"] == 4000
    assert estimate["by_model"][0]["tokens_out"] == 1000
    expected_p1 = cost_usd(4000, 1000, price_in_per_1m=1.0, price_out_per_1m=2.0)
    assert abs(estimate["by_model"][0]["cost_usd"] - expected_p1) < 1e-9
    assert estimate["output_source"] == "gold_run_average"
    assert estimate["totals"]["combinations"] == 4


def test_count_tokens_nonzero():
    n = count_tokens("hello world " * 20)
    assert n > 0
