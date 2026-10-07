"""Тесты оверлея опций прогона извлечения."""

from __future__ import annotations

from pathlib import Path

from paper2data.core.project import close_project, create_project
from paper2data.db.models import Block, Document, Section
from paper2data.db.session import dispose_db, session_scope
from paper2data.extraction import engine as extraction_engine
from paper2data.graph import service as graph_service
from paper2data.llm.profiles import add_profile
from paper2data.schema import service as schema_service

ABSTRACT_TEXT = "ABSTRACT_ONLY_MARKER: this belongs to abstract section only."
EXPERIMENTAL_TEXT = (
    "EXPERIMENTAL_ONLY_MARKER: Device stack fabricated with guest emitter."
)
QUOTE = "Device stack fabricated with guest emitter."


def _add_section(
    session,
    doc_id: int,
    *,
    section_type: str,
    title: str,
    text: str,
    order_index: int,
) -> None:
    sec = Section(
        document_id=doc_id,
        section_type=section_type,
        title=title,
        order_index=order_index,
        useful=True,
    )
    session.add(sec)
    session.flush()
    session.add(
        Block(
            document_id=doc_id,
            section_id=sec.id,
            kind="paragraph",
            text=text,
            page=1,
            order_index=order_index,
        )
    )


def _setup(tmp_path: Path, name: str = "RunOptions"):
    project = create_project(tmp_path / "proj", name=name)
    profile = add_profile(
        name="Test LLM",
        base_url="http://127.0.0.1:9/v1",
        model="test-model",
        context_size=8192,
    )
    return project, profile


def test_section_include_overlay_narrows_chunks(tmp_path: Path):
    project, profile = _setup(tmp_path, "SectionInclude")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Sections")
            doc_id = int(doc["id"])
            _add_section(
                session,
                doc_id,
                section_type="abstract",
                title="Abstract",
                text=ABSTRACT_TEXT,
                order_index=0,
            )
            _add_section(
                session,
                doc_id,
                section_type="experimental",
                title="Experimental",
                text=EXPERIMENTAL_TEXT,
                order_index=1,
            )
            session.get(Document, doc_id).status = "parsed"

            wide = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"pack_chunks": False},
            )
            narrow = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={
                    "section_include": ["experimental"],
                    "pack_chunks": False,
                },
            )
            assert narrow["options"]["section_include"] == ["experimental"]
            assert narrow["options"]["pack_chunks"] is False

            wide_preview = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                step_id="extract_entities_first",
                run_id=int(wide["id"]),
            )
            narrow_preview = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                step_id="extract_entities_first",
                run_id=int(narrow["id"]),
            )

            assert wide_preview["chunks_count"] >= 2
            assert narrow_preview["chunks_count"] == 1
            assert "EXPERIMENTAL_ONLY_MARKER" in narrow_preview["prompt"]
            assert "ABSTRACT_ONLY_MARKER" not in narrow_preview["prompt"]
            assert "ABSTRACT_ONLY_MARKER" in wide_preview["prompt"]
    finally:
        dispose_db()
        close_project()


def test_target_entities_appear_in_prompt_preview(tmp_path: Path):
    project, profile = _setup(tmp_path, "TargetEntities")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Targets")
            doc_id = int(doc["id"])
            _add_section(
                session,
                doc_id,
                section_type="experimental",
                title="Experimental",
                text=EXPERIMENTAL_TEXT,
                order_index=0,
            )
            session.get(Document, doc_id).status = "parsed"

            created = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"target_entities": ["Compound", "Property"]},
            )
            preview = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                step_id="extract_entities_first",
                run_id=int(created["id"]),
            )
            prompt = preview["prompt"]
            assert "Compound" in prompt
            assert "Property" in prompt
            # Целевые типы шага после оверлея — не полный список рецепта.
            assert "Целевые типы сущностей: Compound, Property" in prompt
            assert "CompoundFamily" not in prompt.split("Целевые типы сущностей:")[1].split(
                "\n"
            )[0]
    finally:
        dispose_db()
        close_project()


def test_graph_scope_none_hides_labels_but_dedup_applies(tmp_path: Path, monkeypatch):
    project, profile = _setup(tmp_path, "GraphScopeNone")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="GraphScope")
            doc_id = int(doc["id"])
            _add_section(
                session,
                doc_id,
                section_type="experimental",
                title="Experimental",
                text=EXPERIMENTAL_TEXT,
                order_index=0,
            )
            session.get(Document, doc_id).status = "parsed"

            graph_service.create_node(
                session,
                doc_id,
                {
                    "entity_type": "Compound",
                    "label": "Device 1",
                    "attributes": {"code": "Device 1"},
                    "status": "accepted",
                },
            )

            created = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"graph_scope": "none"},
            )
            run_id = int(created["id"])
            preview = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=doc_id,
                step_id="extract_entities_first",
                run_id=run_id,
            )
            assert "(граф пуст)" in preview["prompt"]
            assert "Device 1" not in preview["prompt"]

        def fake_completion(_profile, *, system_prompt, user_prompt):
            return {
                "data": {
                    "entities": [
                        {
                            "type": "Compound",
                            "label": "Device 1",
                            "temp_id": "e1",
                            "quote": QUOTE,
                            "attributes": {"code": "Device 1"},
                        }
                    ],
                    "relations": [],
                },
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

        monkeypatch.setattr(
            extraction_engine.llm_client,
            "structured_completion",
            fake_completion,
        )

        with session_scope() as session:
            result = extraction_engine.run_step(
                session,
                project,
                run_id=run_id,
                step_id="extract_entities_first",
            )
            assert result["created_nodes"] == []
            assert int(result["run"]["stats"].get("deduped_entities") or 0) >= 1
            graph = graph_service.get_graph(session, doc_id)
            devices = [
                n
                for n in graph["nodes"]
                if str(n.get("label") or "") == "Device 1"
            ]
            assert len(devices) == 1
            assert devices[0]["status"] == "accepted"
    finally:
        dispose_db()
        close_project()


def test_on_empty_fail_marks_run_failed(tmp_path: Path, monkeypatch):
    project, profile = _setup(tmp_path, "OnEmptyFail")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="EmptyFail")
            doc_id = int(doc["id"])
            _add_section(
                session,
                doc_id,
                section_type="experimental",
                title="Experimental",
                text=EXPERIMENTAL_TEXT,
                order_index=0,
            )
            session.get(Document, doc_id).status = "parsed"
            created = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"on_empty": "fail", "phases": "entities"},
            )
            run_id = int(created["id"])

        def fake_completion(_profile, *, system_prompt, user_prompt):
            return {
                "data": {"entities": [], "relations": []},
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }

        monkeypatch.setattr(
            extraction_engine.llm_client,
            "structured_completion",
            fake_completion,
        )

        with session_scope() as session:
            result = extraction_engine.run_step(
                session,
                project,
                run_id=run_id,
                step_id="extract_entities_first",
            )
            run = result["run"]
            assert run["status"] == "failed"
            assert run["status"] != "awaiting_review"
            err = run["error_message"] or ""
            assert "deduped_" in err
            assert "empty_retries" in err
            assert "0 новых" in err or "Пустой результат" in err
    finally:
        dispose_db()
        close_project()


def test_phases_relations_calls_only_extract_relations(tmp_path: Path, monkeypatch):
    project, profile = _setup(tmp_path, "PhasesRelations")
    templates: list[str] = []
    real_render = extraction_engine.render_prompt

    def spy_render(recipe, tmpl, ctx):
        templates.append(tmpl)
        return real_render(recipe, tmpl, ctx)

    monkeypatch.setattr(extraction_engine, "render_prompt", spy_render)

    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Phases")
            doc_id = int(doc["id"])
            _add_section(
                session,
                doc_id,
                section_type="experimental",
                title="Experimental",
                text=EXPERIMENTAL_TEXT,
                order_index=0,
            )
            session.get(Document, doc_id).status = "parsed"
            created = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"phases": "relations"},
            )
            run_id = int(created["id"])
            assert created["options"]["phases"] == "relations"

            extraction_engine.run_step(
                session,
                project,
                run_id=run_id,
                step_id="extract_entities_first",
                dry_run=True,
            )

        assert templates
        assert "extract_relations" in templates
        assert "extract_entities" not in templates
    finally:
        dispose_db()
        close_project()


def test_copy_abbreviations_from_run_id(tmp_path: Path):
    project, profile = _setup(tmp_path, "CopyAbbr")
    try:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
            doc = graph_service.create_document(session, title="Abbr")
            doc_id = int(doc["id"])
            src = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
            )
            from paper2data.db.models import ExtractionRun

            row = session.get(ExtractionRun, int(src["id"]))
            assert row is not None
            row.abbreviation_map_json = extraction_engine._dumps(
                [{"code": "1", "expansion": "Eu(DBM)3BPhen"}]
            )
            session.flush()

            copied = extraction_engine.create_run(
                session,
                project,
                document_id=doc_id,
                llm_profile_id=profile.id,
                options={"copy_abbreviations_from_run_id": int(src["id"])},
            )
            assert copied["options"]["copy_abbreviations_from_run_id"] == int(src["id"])
            assert copied["abbreviation_map"] == [
                {"code": "1", "expansion": "Eu(DBM)3BPhen"}
            ]
    finally:
        dispose_db()
        close_project()
