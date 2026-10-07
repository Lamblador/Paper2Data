"""Политика OLED-стека, аудит anode/cathode, добор неполных устройств."""

from __future__ import annotations

from pathlib import Path

from paper2data.core.project import close_project, create_project
from paper2data.db.models import Block, Document, Section
from paper2data.db.session import dispose_db, session_scope
from paper2data.extraction import engine as extraction_engine
from paper2data.extraction.device_stack import (
    audit_incomplete_device_stacks,
    format_incomplete_stacks_summary,
    is_device_metrics_step,
    is_device_stack_step,
    is_luminescence_step,
    luminescence_policy_instructions,
    metrics_policy_instructions,
    stack_policy_instructions,
)
from paper2data.evaluation import jobs as jobs_mod
from paper2data.extraction.recipes import resolve_recipe
from paper2data.graph import service as graph_service
from paper2data.llm.profiles import add_profile
from paper2data.schema import service as schema_service


def test_stack_policy_local_vs_cloud():
    local = stack_policy_instructions(local_llm=True)
    cloud = stack_policy_instructions(local_llm=False)
    assert "ОТМЕНЯЕТ" in local
    assert "Не более 20" in local
    assert "ровно один неполный Device" in local
    assert "ОТМЕНЯЕТ" in cloud
    assert "не ограничивай" in cloud
    assert "Не более 20" not in cloud
    assert "reproducing" in local
    assert "reproducing" in cloud
    assert "OLED neat" in local
    assert "OLED neat" in cloud
    assert "role обязательно" in local
    assert "role обязательно" in cloud


def test_is_device_stack_step_by_id_and_targets():
    assert is_device_stack_step({"id": "extract_device_stack"})
    assert is_device_stack_step(
        {
            "id": "custom",
            "targets": {"entities": ["Device", "Layer", "Material"]},
        }
    )
    assert not is_device_stack_step(
        {"id": "extract_compounds", "targets": {"entities": ["Compound"]}}
    )


def test_metrics_policy_separates_eqe_and_ece():
    text = metrics_policy_instructions()
    assert "external quantum efficiency" in text
    assert "external current efficiency" in text
    assert "property_type=eqe" in text
    assert "property_type=current_efficiency" in text
    assert "ECE" in text
    assert "cd/A" in text
    assert is_device_metrics_step({"id": "extract_device_metrics"})
    assert is_device_metrics_step(
        {
            "id": "custom",
            "targets": {
                "entities": ["Property", "Condition"],
                "relations": ["HAS_CHARACTERISTIC"],
            },
        }
    )
    assert not is_device_metrics_step(
        {
            "id": "extract_luminescence",
            "targets": {
                "entities": ["Property", "Condition"],
                "relations": ["HAS_PROPERTY", "MEASURED_UNDER"],
            },
        }
    )


def test_luminescence_policy_separates_etasens_from_qy():
    text = luminescence_policy_instructions()
    assert "ηsens" in text
    assert "sensitization_efficiency" in text
    assert "не квантовый выход" in text
    assert "property_type=quantum_yield" in text
    assert is_luminescence_step({"id": "extract_luminescence"})
    assert is_luminescence_step(
        {
            "id": "custom",
            "targets": {
                "entities": ["Property"],
                "relations": ["HAS_PROPERTY"],
            },
        }
    )
    assert not is_luminescence_step({"id": "extract_device_metrics"})
    assert not is_luminescence_step(
        {
            "id": "custom_metrics",
            "targets": {
                "entities": ["Property"],
                "relations": ["HAS_CHARACTERISTIC", "HAS_PROPERTY"],
            },
        }
    )


def test_audit_incomplete_only_eml_vs_full():
    graph = {
        "nodes": [
            {
                "id": 1,
                "entity_type": "Device",
                "label": "Device 5",
                "status": "accepted",
                "attributes": {},
            },
            {
                "id": 2,
                "entity_type": "Layer",
                "label": "EML layer (Device 5)",
                "status": "accepted",
                "attributes": {"role": "EML"},
            },
            {
                "id": 3,
                "entity_type": "Device",
                "label": "Device 1",
                "status": "accepted",
                "attributes": {},
            },
            {
                "id": 4,
                "entity_type": "Layer",
                "label": "ITO layer (Device 1)",
                "status": "accepted",
                "attributes": {"role": "anode"},
            },
            {
                "id": 5,
                "entity_type": "Layer",
                "label": "Al layer (Device 1)",
                "status": "accepted",
                "attributes": {"role": "cathode"},
            },
        ],
        "edges": [
            {
                "id": 10,
                "relation_type": "HAS_LAYER",
                "source_node_id": 1,
                "target_node_id": 2,
                "status": "accepted",
            },
            {
                "id": 11,
                "relation_type": "HAS_LAYER",
                "source_node_id": 3,
                "target_node_id": 4,
                "status": "accepted",
            },
            {
                "id": 12,
                "relation_type": "HAS_LAYER",
                "source_node_id": 3,
                "target_node_id": 5,
                "status": "accepted",
            },
        ],
    }
    gaps = audit_incomplete_device_stacks(graph, run_id=None)
    assert len(gaps) == 1
    assert gaps[0]["label"] == "Device 5"
    assert gaps[0]["missing_roles"] == ["anode", "cathode"]
    summary = format_incomplete_stacks_summary(gaps)
    assert "Device 5" in summary
    assert "анода" in summary


def test_audit_sees_layers_by_label_without_edge():
    """Фаза entities ещё без HAS_LAYER — роли читаем из label+attrs."""
    graph = {
        "nodes": [
            {
                "id": 1,
                "entity_type": "Device",
                "label": "Device 3",
                "status": "accepted",
                "attributes": {},
            },
            {
                "id": 2,
                "entity_type": "Layer",
                "label": "ITO (Device 3)",
                "status": "proposed",
                "run_id": 99,
                "attributes": {"role": "anode"},
            },
            {
                "id": 3,
                "entity_type": "Layer",
                "label": "Al (Device 3)",
                "status": "proposed",
                "run_id": 99,
                "attributes": {"role": "cathode"},
            },
        ],
        "edges": [],
    }
    assert audit_incomplete_device_stacks(graph, run_id=99) == []
    # Другой прогон не видит proposed
    gaps = audit_incomplete_device_stacks(graph, run_id=1)
    assert len(gaps) == 1


def test_oled_recipe_has_no_hard_entity_cap():
    body = resolve_recipe("oled_extract")
    stack = next(s for s in body["steps"] if s["id"] == "extract_device_stack")
    instr = str(stack.get("instructions") or "")
    assert "Не более 20" not in instr
    assert "ещё нет слоёв" not in instr


def test_full_extract_stage_plan_keeps_stack_unsplit():
    recipe = resolve_recipe("oled_extract")
    plan = jobs_mod._full_extract_stage_plan(recipe)
    stack_stages = [p for p in plan if p.get("step_id") == "extract_device_stack"]
    assert len(stack_stages) == 1
    assert stack_stages[0]["phase"] is None
    # Обычные entities_first по-прежнему дробятся
    compound = [p for p in plan if p.get("step_id") == "extract_compounds"]
    assert any(p.get("phase") == "entities" for p in compound)
    assert any(p.get("phase") == "relations" for p in compound)


def test_overlay_prompt_contains_policy_override(tmp_path: Path):
    project = create_project(tmp_path / "proj", name="StackPolicy")
    local = add_profile(
        name="Local",
        base_url="http://127.0.0.1:1234/v1",
        model="local-model",
    )
    cloud = add_profile(
        name="Cloud",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
    )
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "oled")
            doc = graph_service.create_document(session, title="Stack")
            doc_id = int(doc["id"])
            sec = Section(
                document_id=doc_id,
                section_type="results",
                title="Results",
                order_index=0,
                useful=True,
            )
            session.add(sec)
            session.flush()
            session.add(
                Block(
                    document_id=doc_id,
                    section_id=sec.id,
                    kind="paragraph",
                    text="Device 1: ITO|HAT-CN (10 nm)|Al (100 nm). " * 20,
                    page=1,
                    order_index=0,
                )
            )
            session.get(Document, doc_id).status = "parsed"

            local_run = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                recipe_id="oled_extract",
                llm_profile_id=local.id,
            )
            cloud_run = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                recipe_id="oled_extract",
                llm_profile_id=cloud.id,
            )

            local_prev = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                recipe_id="oled_extract",
                step_id="extract_device_stack",
                run_id=int(local_run["id"]),
            )
            cloud_prev = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                recipe_id="oled_extract",
                step_id="extract_device_stack",
                run_id=int(cloud_run["id"]),
            )

            assert "ОТМЕНЯЕТ" in local_prev["prompt"]
            assert "Не более 20" in local_prev["prompt"]
            assert "ОТМЕНЯЕТ" in cloud_prev["prompt"]
            assert "не ограничивай" in cloud_prev["prompt"]
            assert "Не более 20" not in cloud_prev["prompt"]
    finally:
        close_project()
        dispose_db()


def test_local_stack_fill_stops_on_empty_pass(tmp_path: Path, monkeypatch):
    project = create_project(tmp_path / "proj", name="StackFill")
    profile = add_profile(
        name="Local",
        base_url="http://127.0.0.1:9/v1",
        model="local",
    )
    call_count = {"n": 0}

    def fake_completion(prof, *, system_prompt, user_prompt, **kwargs):
        call_count["n"] += 1
        # Первый проход — EML без электродов; дальше пусто
        if call_count["n"] == 1:
            return {
                "data": {
                    "entities": [
                        {
                            "type": "Layer",
                            "label": "EML layer (Device 5)",
                            "attributes": {"role": "EML", "thickness": {"value": 10, "unit": "nm"}},
                            "quote": "Device 5 features an emissive layer of 10 nm 6-Yb neat film",
                            "temp_id": "e1",
                        }
                    ],
                    "relations": [],
                },
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        return {
            "data": {"entities": [], "relations": []},
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        "paper2data.llm.client.structured_completion",
        fake_completion,
    )

    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "oled")
            doc = graph_service.create_document(session, title="Fill stop")
            doc_id = int(doc["id"])
            sec = Section(
                document_id=doc_id,
                section_type="results",
                title="Results",
                order_index=0,
                useful=True,
            )
            session.add(sec)
            session.flush()
            long_text = (
                "Device 5 features an emissive layer of 10 nm 6-Yb neat film. "
                "reproducing the structure of Device 3. " * 30
            )
            session.add(
                Block(
                    document_id=doc_id,
                    section_id=sec.id,
                    kind="paragraph",
                    text=long_text,
                    page=1,
                    order_index=0,
                )
            )
            session.get(Document, doc_id).status = "parsed"
            device = graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Device",
                    "label": "Device 5",
                    "attributes": {"name": "Device 5"},
                    "status": "accepted",
                },
            )
            run = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                recipe_id="oled_extract",
                llm_profile_id=profile.id,
            )
            result = extraction_engine.run_step(
                session,
                project,
                run_id=int(run["id"]),
                step_id="extract_device_stack",
                phase="entities",
            )
            stats = result["run"]["stats"]
            assert stats.get("stack_fill_stopped") == "empty_pass"
            gaps = stats.get("incomplete_device_stacks") or []
            assert any(g.get("label") == "Device 5" for g in gaps)
            assert device["id"]
            # Первый вызов + пустые доборы (и возможно empty_retries на длинном тексте)
            assert call_count["n"] >= 2
            assert call_count["n"] <= MAX_CALLS_CAP
    finally:
        close_project()
        dispose_db()


# Локальный цикл: первый проход + до 7 доборов; empty_retry может удвоить
MAX_CALLS_CAP = 20
