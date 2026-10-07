"""Тесты верификации цитат и загрузки рецептов (M3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper2data.extraction.quotes import (
    score_quote_in_block,
    verify_quote_against_blocks,
    verify_quote_in_text,
)
from paper2data.extraction.recipes import (
    default_strategy_for_intelligence,
    load_recipe_file,
    parse_recipe_yaml,
    recipes_templates_root,
    resolve_recipe,
    validate_recipe,
)
from paper2data.extraction.generator import generate_recipe_from_schema_and_gold
from paper2data.schema.loader import resolve_template


def test_verify_quote_exact_and_fuzzy():
    text = (
        "The complex 1, Eu(DBM)3BPhen, exhibits a lifetime of 1.2 ms in toluene solution."
    )
    ok = verify_quote_in_text("Eu(DBM)3BPhen", text, threshold=90)
    assert ok.verified is True
    assert ok.score >= 90

    fuzzy = verify_quote_in_text(
        "exhibits a lifetime of 1.2 ms in toluene",
        text,
        threshold=90,
    )
    assert fuzzy.verified is True

    bad = verify_quote_in_text("completely unrelated phrase xyz", text, threshold=90)
    assert bad.verified is False
    assert bad.score < 90


def test_verify_quote_against_blocks_picks_best():
    blocks = [
        {"id": 1, "text": "Introduction filler text.", "page": 1},
        {
            "id": 2,
            "text": "Compound 1 was prepared as Eu(DBM)3BPhen.",
            "page": 3,
        },
        {"id": 3, "text": "Acknowledgments to colleagues.", "page": 10},
    ]
    match = verify_quote_against_blocks(
        "prepared as Eu(DBM)3BPhen",
        blocks,
        threshold=90,
    )
    assert match.verified is True
    assert match.block_id == 2
    assert match.page == 3


def test_verify_quote_skips_page_number_blocks():
    blocks = [
        {"id": 1, "text": "3", "page": 3},
        {"id": 2, "text": "6", "page": 6},
        {
            "id": 3,
            "text": "General method for the preparation of [Ln(L)3(phen)] complexes in ethanol.",
            "page": 4,
        },
    ]
    match = verify_quote_against_blocks(
        "General method for the preparation of [Ln(L)3(phen)] complexes",
        blocks,
        threshold=90,
    )
    assert match.block_id == 3
    assert match.page == 4
    assert match.verified is True
    assert score_quote_in_block("lifetime of 1.2 ms in toluene", "3") == 0


def test_verify_quote_ellipsis_prefers_row_over_page_number():
    blocks = [
        {"id": 1, "text": "3", "page": 3},
        {
            "id": 2,
            "text": "Yb(1-Naph)3(phen) 18.4 4.9 4.7 25100 Yb(2-Naph)3(phen) 16.6",
            "page": 6,
        },
    ]
    match = verify_quote_against_blocks(
        "Yb(1-Naph)3(phen) ... 25100",
        blocks,
        threshold=90,
    )
    assert match.block_id == 2
    assert match.page == 6
    assert match.verified is True


def test_load_example_coordination_recipe():
    root = recipes_templates_root()
    path = root / "example_coordination_extract.yaml"
    assert path.is_file()
    recipe = load_recipe_file(path)
    assert recipe["kind"] == "recipe"
    assert recipe["id"] == "example_coordination_extract"
    assert recipe["schema_id"] == "coordination_compounds"
    assert len(recipe["steps"]) >= 2
    assert "resolve_abbreviations" in {s["id"] for s in recipe["steps"]}
    assert "prompt_templates" in recipe
    assert "extract_entities" in recipe["prompt_templates"]


def test_resolve_recipe_bundled():
    recipe = resolve_recipe("example_coordination_extract")
    assert recipe["name"]
    validated = validate_recipe(recipe)
    assert validated["pipeline"]


def test_invalid_recipe_missing_steps():
    with pytest.raises(ValueError):
        parse_recipe_yaml(
            "version: '1'\nid: x\nname: X\nkind: recipe\nschema_id: s\nsteps: []\n"
        )


def test_default_strategy_from_intelligence():
    assert default_strategy_for_intelligence("high") == "one_shot"
    assert default_strategy_for_intelligence("low") == "iterative"
    assert default_strategy_for_intelligence("medium") == "entities_first"


def test_generate_recipe_from_schema(tmp_path: Path):
    schema = resolve_template("coordination_compounds")
    gold = {
        "nodes": [
            {
                "entity_type": "Compound",
                "label": "1",
                "attributes": {"code": "1", "formula": "Eu(DBM)3BPhen"},
                "evidences": [{"quote": "complex 1, Eu(DBM)3BPhen"}],
            }
        ],
        "edges": [],
    }
    recipe = generate_recipe_from_schema_and_gold(
        schema,
        gold_payload=gold,
        intelligence_level="medium",
        recipe_id="test_coord_extract",
    )
    assert recipe["id"] == "test_coord_extract"
    assert recipe["defaults"]["strategy"] == "entities_first"
    assert any(s["id"] == "resolve_abbreviations" for s in recipe["steps"])
    step_ids = [s["id"] for s in recipe["steps"]]
    assert "extract_compounds" in step_ids
    assert "extract_luminescence" in step_ids
    compounds = next(s for s in recipe["steps"] if s["id"] == "extract_compounds")
    assert "Compound" in compounds["targets"]["entities"]
    assert "Property" not in compounds["targets"]["entities"]
    high = generate_recipe_from_schema_and_gold(
        schema, intelligence_level="high", recipe_id="high_one"
    )
    assert high["defaults"]["strategy"] == "one_shot"


def test_generate_recipe_oled_device_stack_step():
    schema = resolve_template("oled")
    recipe = generate_recipe_from_schema_and_gold(
        schema, intelligence_level="medium", recipe_id="oled_gen"
    )
    by_id = {s["id"]: s for s in recipe["steps"]}
    assert "extract_device_stack" in by_id
    stack = by_id["extract_device_stack"]
    assert "Layer" in stack["targets"]["entities"]
    assert "Material" in stack["targets"]["entities"]
    assert "IS_COMPOUND" in stack["targets"]["relations"]
    # Стек не тащит полный список Property из люминесценции
    assert "Property" not in stack["targets"]["entities"]
    assert "HAS_PROPERTY" not in stack["targets"]["relations"]
    assert recipe["pipeline"][0] == "resolve_abbreviations"
    assert "extract_device_stack" in recipe["pipeline"]


def test_bundled_domain_recipes_validate():
    from paper2data.extraction.recipes import list_bundled_recipes

    bundled_ids = {r["id"] for r in list_bundled_recipes()}
    assert "oled_extract" in bundled_ids
    assert "luminescence_extract" in bundled_ids
    assert "toxicity_extract" in bundled_ids
    for rid in ("oled_extract", "luminescence_extract", "toxicity_extract"):
        body = resolve_recipe(rid)
        assert body["kind"] == "recipe"
        assert body["steps"]
        assert body["pipeline"]
        stack = next(
            (s for s in body["steps"] if s["id"] == "extract_device_stack"),
            None,
        )
        if rid == "oled_extract":
            assert stack is not None
            assert "Device" in stack["targets"]["entities"]
            assert "esi" not in (stack.get("section_include") or [])


def test_run_step_history_counts_and_review_queue(tmp_path: Path, monkeypatch):
    from paper2data.core.project import close_project, create_project
    from paper2data.db.models import Block
    from paper2data.db.session import dispose_db, session_scope
    from paper2data.extraction import engine as extraction_engine
    from paper2data.extraction.review import list_review_queue
    from paper2data.graph import service as graph_service
    from paper2data.llm.profiles import add_profile
    from paper2data.schema import service as schema_service

    project = create_project(tmp_path / "proj", name="M3History")
    profile = add_profile(
        name="Test LLM",
        base_url="http://127.0.0.1:9/v1",
        model="test-model",
        context_size=8192,
    )
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="История шагов")
            doc_id = int(doc["id"])
            session.add(
                Block(
                    document_id=doc_id,
                    kind="paragraph",
                    text="Compound 1 is Eu(DBM)3BPhen.",
                    page=1,
                    order_index=0,
                )
            )
            created = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
            )
            run_id = int(created["id"])
            assert created["pipeline"]
            assert created["steps_total"] == len(created["pipeline"])
            assert created["step_index"] == 0
            assert created["steps_history"] == []
            assert created["counts"] == {
                "proposed": 0,
                "accepted": 0,
                "rejected": 0,
                "nodes": 0,
                "edges": 0,
            }

            proposed = graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Compound",
                    "label": "1",
                    "attributes": {"code": "1"},
                    "status": "proposed",
                    "run_id": run_id,
                },
            )
            accepted = graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Property",
                    "attributes": {"property_type": "lifetime", "value": 1.2, "unit": "ms"},
                    "status": "accepted",
                    "run_id": run_id,
                },
            )
            graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Compound",
                    "label": "manual-in-run",
                    "attributes": {"code": "m"},
                    "status": "manual",
                    "run_id": run_id,
                },
            )
            graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Compound",
                    "label": "other-run",
                    "attributes": {"code": "x"},
                    "status": "proposed",
                },
            )
            graph_service.create_edge(
                session,
                doc_id,
                {
                    "relation_type": "HAS_PROPERTY",
                    "source_node_id": proposed["id"],
                    "target_node_id": accepted["id"],
                    "status": "rejected",
                    "run_id": run_id,
                },
            )

            first_id = created["pipeline"][0]
            result = extraction_engine.run_step(
                session, project, run_id=run_id, dry_run=True
            )
            history = result["run"]["stats"]["steps_history"]
            assert len(history) == 1
            assert history[0]["step_id"] == first_id
            assert history[0]["status"] == "done"
            assert set(history[0]) == {
                "step_id",
                "status",
                "started_at",
                "finished_at",
                "nodes",
                "edges",
                "abbreviations",
                "prompt_tokens",
                "completion_tokens",
                "error",
            }
            assert history[0]["started_at"]
            assert history[0]["finished_at"]
            assert history[0]["error"] is None
            assert history[0]["prompt_tokens"] == 0
            assert history[0]["completion_tokens"] == 0
            assert result["run"]["steps_history"] == history
            assert result["run"]["pipeline"] == created["pipeline"]
            assert result["run"]["steps_total"] == len(created["pipeline"])
            assert result["run"]["step_index"] == 1
            assert result["run"]["counts"] == {
                "proposed": 1,
                "accepted": 1,
                "rejected": 1,
                "nodes": 3,
                "edges": 1,
            }

            again = extraction_engine.run_step(
                session, project, run_id=run_id, step_id=first_id, dry_run=True
            )
            assert len(again["run"]["stats"]["steps_history"]) == 1
            assert again["run"]["stats"]["steps_history"][0]["step_id"] == first_id
            assert again["run"]["stats"]["steps_history"][0]["status"] == "done"

            if len(created["pipeline"]) > 1:
                later_id = created["pipeline"][1]
                later = extraction_engine.run_step(
                    session, project, run_id=run_id, step_id=later_id, dry_run=True
                )
                ordered = [item["step_id"] for item in later["run"]["steps_history"]]
                assert ordered == [first_id, later_id]
                assert later["run"]["step_index"] == 2

            queue = list_review_queue(session, doc_id, run_id=run_id, project=project)
            assert queue["pipeline"] == created["pipeline"]
            assert queue["steps_total"] == created["steps_total"]
            assert queue["step_index"] >= 1
            assert queue["steps_history"]
            assert queue["steps_history"][0]["step_id"] == first_id
            assert "total" in queue["counts"]

            def _broken(*_args, **_kwargs):
                raise RuntimeError("recipe missing")

            monkeypatch.setattr(extraction_engine, "get_active_recipe_body", _broken)
            listed = extraction_engine.list_runs(session, doc_id, project)
            assert len(listed) == 1
            assert listed[0]["pipeline"] == []
            assert listed[0]["steps_total"] == 0
            assert listed[0]["step_index"] == 0
            assert listed[0]["steps_history"]
            assert listed[0]["counts"]["nodes"] == 3
    finally:
        dispose_db()
        close_project()


def test_run_step_failure_records_history(tmp_path: Path, monkeypatch):
    from paper2data.core.project import close_project, create_project
    from paper2data.db.models import ExtractionRun
    from paper2data.db.session import dispose_db, session_scope
    from paper2data.extraction import engine as extraction_engine
    from paper2data.graph import service as graph_service
    from paper2data.llm.profiles import add_profile
    from paper2data.schema import service as schema_service

    project = create_project(tmp_path / "proj-fail", name="M3Fail")
    profile = add_profile(
        name="Test LLM",
        base_url="http://127.0.0.1:9/v1",
        model="test-model",
        context_size=8192,
    )
    seen: dict[str, object] = {}
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Сбой шага")
            created = extraction_engine.create_run(
                session,
                project,
                document_id=int(doc["id"]),
                llm_profile_id=profile.id,
            )
            run_id = int(created["id"])

        def _boom(session, document_id, **kwargs):
            row = session.get(ExtractionRun, run_id)
            assert row is not None
            seen["stats"] = extraction_engine._loads(row.stats_json, {})
            raise RuntimeError("boom")

        monkeypatch.setattr(
            extraction_engine.chunk_mod,
            "load_document_blocks",
            _boom,
        )
        with pytest.raises(RuntimeError, match="boom"):
            with session_scope() as session:
                extraction_engine.run_step(session, project, run_id=run_id, dry_run=True)

        running = seen["stats"]["steps_history"]
        assert len(running) == 1
        assert running[0]["status"] == "running"
        assert running[0]["started_at"]
        assert running[0]["finished_at"] is None

        with session_scope() as session:
            payload = extraction_engine.get_run(session, run_id, project)
        assert payload["status"] == "failed"
        assert payload["steps_history"][0]["status"] == "failed"
        assert payload["steps_history"][0]["error"]
        assert "boom" in payload["steps_history"][0]["error"]
        assert payload["steps_history"][0]["started_at"]
        assert payload["steps_history"][0]["finished_at"]
        assert payload["stats"]["steps_history"][0]["status"] == "failed"
    finally:
        dispose_db()
        close_project()
