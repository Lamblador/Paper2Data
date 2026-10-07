"""Тесты full_extract job, дедупа в _apply_llm_payload и фильтра gold в batch."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from paper2data.api.app import create_app
from paper2data.core.project import create_project
from paper2data.db.models import Block, Document, Section
from paper2data.db.session import dispose_db, session_scope
from paper2data.evaluation import jobs as jobs_mod
from paper2data.extraction import engine as extraction_engine
from paper2data.graph import service as graph_service
from paper2data.llm.profiles import add_profile
from paper2data.schema import service as schema_service


QUOTE = "The complex 1, Eu(DBM)3BPhen, exhibits a lifetime of 1.2 ms."


def _add_text(session, doc_id: int, text: str = QUOTE) -> None:
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
            text=text,
            page=1,
            order_index=0,
        )
    )
    doc = session.get(Document, doc_id)
    assert doc is not None
    doc.status = "parsed"
    session.flush()


def _setup_project(tmp_path: Path, *, with_schema: bool = False):
    project = create_project(tmp_path / "proj", name="FullExtract")
    profile = add_profile(
        name="Test LLM",
        base_url="http://127.0.0.1:9/v1",
        model="test-model",
        context_size=8192,
    )
    if with_schema:
        with session_scope() as session:
            schema_service.apply_template(session, project, "coordination_compounds")
    return project, profile


def _patch_extraction(monkeypatch, *, ingest_impl=None, create_run_impl=None, run_step_impl=None):
    if ingest_impl is not None:
        monkeypatch.setattr(
            "paper2data.ingest.service.ingest_document",
            ingest_impl,
        )
    if create_run_impl is not None:
        monkeypatch.setattr(extraction_engine, "create_run", create_run_impl)
    if run_step_impl is not None:
        monkeypatch.setattr(extraction_engine, "run_step", run_step_impl)


# ---------------------------------------------------------------------------
# full_extract job
# ---------------------------------------------------------------------------


def test_full_extract_unparsed_goes_through_ingest(tmp_path: Path, monkeypatch):
    project, profile = _setup_project(tmp_path)
    ingest_calls: list[int] = []
    step_calls: list[tuple] = []

    try:
        with session_scope() as session:
            doc = graph_service.create_document(session, title="Unparsed")
            doc_id = doc["id"]
            row = session.get(Document, doc_id)
            assert row is not None
            row.status = "indexed"

        def fake_ingest(session, _project, document_id: int):
            ingest_calls.append(document_id)
            _add_text(session, document_id)
            return {"id": document_id, "status": "parsed"}

        def fake_create_run(session, _project, **kwargs):
            return {"id": 101}

        def fake_run_step(session, _project, *, run_id, step_id, phase=None):
            step_calls.append((step_id, phase))
            return {
                "created_nodes": [],
                "created_edges": [],
                "run": {"stats": {"tokens": 3}},
            }

        _patch_extraction(
            monkeypatch,
            ingest_impl=fake_ingest,
            create_run_impl=fake_create_run,
            run_step_impl=fake_run_step,
        )

        job = jobs_mod.create_job(
            kind="full_extract",
            payload={
                "document_ids": [doc_id],
                "llm_profile_id": profile.id,
                "ingest_missing": True,
                "reparse": False,
                "items": [],
                "cursor": 0,
            },
            enqueue=False,
        )
        jobs_mod._run_full_extract(job["id"], dict(job["payload"]))
        finished = jobs_mod.get_job(job["id"])

        assert ingest_calls == [doc_id]
        assert finished["status"] == "completed"
        assert finished["result"]["done"] == 1
        assert finished["result"]["failed"] == 0
        assert finished["result"]["items"][0]["stage"] == "done"
    finally:
        dispose_db()


def test_full_extract_stage_order_resolve_then_entities_relations(
    tmp_path: Path, monkeypatch
):
    project, profile = _setup_project(tmp_path)
    step_calls: list[tuple[str | None, str | None]] = []

    try:
        with session_scope() as session:
            doc = graph_service.create_document(session, title="Ordered")
            doc_id = doc["id"]
            _add_text(session, doc_id)

        def fake_create_run(session, _project, **kwargs):
            return {"id": 202}

        def fake_run_step(session, _project, *, run_id, step_id, phase=None):
            step_calls.append((step_id, phase))
            return {
                "created_nodes": [{"id": 1}] if phase == "entities" else [],
                "created_edges": [{"id": 1}] if phase == "relations" else [],
                "run": {"stats": {"tokens": 7}},
            }

        _patch_extraction(
            monkeypatch,
            create_run_impl=fake_create_run,
            run_step_impl=fake_run_step,
        )

        job = jobs_mod.create_job(
            kind="full_extract",
            payload={
                "document_ids": [doc_id],
                "llm_profile_id": profile.id,
                "items": [],
                "cursor": 0,
            },
            enqueue=False,
        )
        jobs_mod._run_full_extract(job["id"], dict(job["payload"]))
        finished = jobs_mod.get_job(job["id"])

        assert finished["status"] == "completed"
        assert step_calls == [
            ("resolve_abbreviations", None),
            ("extract_entities_first", "entities"),
            ("extract_entities_first", "relations"),
        ]
        item = finished["result"]["items"][0]
        assert [s["step_id"] for s in item["steps"]] == [
            "resolve_abbreviations",
            "extract_entities_first",
            "extract_entities_first",
        ]
        assert [s.get("phase") for s in item["steps"]] == [
            None,
            "entities",
            "relations",
        ]
    finally:
        dispose_db()


def test_full_extract_one_failure_does_not_stop_others(tmp_path: Path, monkeypatch):
    project, profile = _setup_project(tmp_path)
    run_by_doc: dict[int, int] = {}

    try:
        with session_scope() as session:
            d1 = graph_service.create_document(session, title="OK")
            d2 = graph_service.create_document(session, title="Fail")
            doc_ok = d1["id"]
            doc_fail = d2["id"]
            _add_text(session, doc_ok)
            _add_text(session, doc_fail)

        def fake_create_run(session, _project, **kwargs):
            rid = 300 + kwargs["document_id"]
            run_by_doc[kwargs["document_id"]] = rid
            return {"id": rid}

        def fake_run_step(session, _project, *, run_id, step_id, phase=None):
            if run_id == run_by_doc.get(doc_fail):
                raise RuntimeError("LLM timeout")
            return {
                "created_nodes": [],
                "created_edges": [],
                "run": {"stats": {"tokens": 1}},
            }

        _patch_extraction(
            monkeypatch,
            create_run_impl=fake_create_run,
            run_step_impl=fake_run_step,
        )

        job = jobs_mod.create_job(
            kind="full_extract",
            payload={
                "document_ids": [doc_ok, doc_fail],
                "llm_profile_id": profile.id,
                "items": [],
                "cursor": 0,
            },
            enqueue=False,
        )
        jobs_mod._run_full_extract(job["id"], dict(job["payload"]))
        finished = jobs_mod.get_job(job["id"])

        assert finished["status"] == "completed"
        assert finished["result"]["done"] == 1
        assert finished["result"]["failed"] == 1
        assert finished["result"]["total"] == 2
        by_doc = {it["document_id"]: it for it in finished["result"]["items"]}
        assert by_doc[doc_ok]["stage"] == "done"
        assert by_doc[doc_fail]["stage"] == "failed"
        assert "LLM timeout" in (by_doc[doc_fail].get("error") or "")
        assert "ошибок: 1" in (finished.get("message") or "")
    finally:
        dispose_db()


def test_full_extract_resume_restarts_only_failed(tmp_path: Path, monkeypatch):
    project, profile = _setup_project(tmp_path)
    create_run_docs: list[int] = []
    step_run_ids: list[int] = []
    fail_once = {"active": True}

    try:
        with session_scope() as session:
            d1 = graph_service.create_document(session, title="Done")
            d2 = graph_service.create_document(session, title="Retry")
            doc_done = d1["id"]
            doc_fail = d2["id"]
            _add_text(session, doc_done)
            _add_text(session, doc_fail)

        def fake_create_run(session, _project, **kwargs):
            create_run_docs.append(kwargs["document_id"])
            return {"id": 400 + kwargs["document_id"]}

        def fake_run_step(session, _project, *, run_id, step_id, phase=None):
            step_run_ids.append(run_id)
            if fail_once["active"] and run_id == 400 + doc_fail:
                raise RuntimeError("transient")
            return {
                "created_nodes": [],
                "created_edges": [],
                "run": {"stats": {"tokens": 2}},
            }

        _patch_extraction(
            monkeypatch,
            create_run_impl=fake_create_run,
            run_step_impl=fake_run_step,
        )

        job = jobs_mod.create_job(
            kind="full_extract",
            payload={
                "document_ids": [doc_done, doc_fail],
                "llm_profile_id": profile.id,
                "items": [],
                "cursor": 0,
            },
            enqueue=False,
        )
        payload = dict(job["payload"])
        jobs_mod._run_full_extract(job["id"], payload)
        mid = jobs_mod.get_job(job["id"])
        assert mid["result"]["failed"] == 1
        assert mid["result"]["done"] == 1

        create_run_docs.clear()
        step_run_ids.clear()
        fail_once["active"] = False

        payload = dict(mid["payload"])
        for it in payload.get("items") or []:
            jobs_mod._reset_failed_item(it, kind="full_extract")
        with session_scope() as session:
            from paper2data.db.models import Job

            row = session.get(Job, job["id"])
            assert row is not None
            row.payload_json = jobs_mod._dumps(payload)
            row.status = "pending"
            row.error_message = None
            row.message = "Возобновление"
            row.result_json = "{}"

        jobs_mod._run_full_extract(job["id"], payload)
        finished = jobs_mod.get_job(job["id"])

        assert finished["status"] == "completed"
        assert finished["result"]["done"] == 2
        assert finished["result"]["failed"] == 0
        # done item skipped — create_run только для ранее failed
        assert create_run_docs == [doc_fail]
        assert all(rid == 400 + doc_fail for rid in step_run_ids)
        by_doc = {it["document_id"]: it for it in finished["result"]["items"]}
        assert by_doc[doc_done]["stage"] == "done"
        assert by_doc[doc_fail]["stage"] == "done"
    finally:
        dispose_db()


# ---------------------------------------------------------------------------
# dedup in _apply_llm_payload
# ---------------------------------------------------------------------------


def test_apply_llm_payload_dedup_same_type_label(tmp_path: Path):
    project, _profile = _setup_project(tmp_path, with_schema=True)
    try:
        with session_scope() as session:
            from sqlalchemy import select

            doc = graph_service.create_document(session, title="Dedup")
            doc_id = doc["id"]
            _add_text(session, doc_id)
            blocks = [
                {
                    "id": b.id,
                    "text": b.text,
                    "page": b.page,
                    "bbox": None,
                }
                for b in session.scalars(
                    select(Block).where(Block.document_id == doc_id)
                ).all()
            ]

            run_id = 55
            applied = extraction_engine._apply_llm_payload(
                session,
                doc_id,
                run_id,
                {
                    "entities": [
                        {
                            "type": "Compound",
                            "label": "1",
                            "temp_id": "e1",
                            "quote": QUOTE,
                            "attributes": {"code": "1", "formula": "Eu(DBM)3BPhen"},
                        },
                        {
                            "type": "Compound",
                            "label": "1",
                            "temp_id": "e2",
                            "quote": QUOTE,
                            "attributes": {"code": "1", "formula": "Eu(DBM)3BPhen"},
                        },
                        {
                            "type": "Property",
                            "label": "lifetime",
                            "temp_id": "e3",
                            "quote": QUOTE,
                            "attributes": {
                                "property_type": "lifetime",
                                "value": 1.2,
                                "unit": "ms",
                            },
                        },
                    ],
                    "relations": [
                        {
                            "type": "HAS_PROPERTY",
                            "source_temp_id": "e2",
                            "target_temp_id": "e3",
                            "quote": QUOTE,
                        }
                    ],
                },
                blocks,
                threshold=50,
            )

            assert applied["deduped_entities"] == 1
            assert len(applied["nodes"]) == 2
            assert len(applied["edges"]) == 1

            graph = graph_service.get_graph(session, doc_id)
            compounds = [
                n
                for n in graph["nodes"]
                if n.get("entity_type") == "Compound" and n.get("label") == "1"
            ]
            assert len(compounds) == 1
            props = [n for n in graph["nodes"] if n.get("entity_type") == "Property"]
            assert len(props) == 1
            edge = graph["edges"][0]
            assert edge["source_node_id"] == compounds[0]["id"]
            assert edge["target_node_id"] == props[0]["id"]
            assert edge["relation_type"] == "HAS_PROPERTY"
    finally:
        dispose_db()


# ---------------------------------------------------------------------------
# api_batch_start gold filter
# ---------------------------------------------------------------------------


def test_api_batch_start_skips_without_gold_and_400_when_empty(
    tmp_path: Path, monkeypatch
):
    project, profile = _setup_project(tmp_path, with_schema=True)

    real_create = jobs_mod.create_job

    def create_no_enqueue(**kwargs):
        kwargs = dict(kwargs)
        kwargs["enqueue"] = False
        return real_create(**kwargs)

    monkeypatch.setattr(jobs_mod, "create_job", create_no_enqueue)

    try:
        with session_scope() as session:
            gold_doc = graph_service.create_document(session, title="With gold")
            plain_doc = graph_service.create_document(session, title="No gold")
            gold_id = gold_doc["id"]
            plain_id = plain_doc["id"]
            node = graph_service.create_node(
                session,
                gold_id,
                {
                    "entity_type": "Compound",
                    "attributes": {"code": "1", "formula": "Eu(DBM)3"},
                    "status": "manual",
                },
            )
            graph_service.save_gold_snapshot(session, gold_id)
            assert node["id"]

        client = TestClient(create_app())

        empty = client.post(
            "/api/evaluation/batch",
            json={
                "document_ids": [plain_id],
                "llm_profile_ids": [profile.id],
                "evaluate": True,
            },
        )
        assert empty.status_code == 400
        assert "эталон" in (empty.json().get("detail") or "").lower()

        mixed = client.post(
            "/api/evaluation/batch",
            json={
                "document_ids": [gold_id, plain_id],
                "llm_profile_ids": [profile.id],
                "evaluate": True,
            },
        )
        assert mixed.status_code == 200
        body = mixed.json()
        assert body["skipped_without_gold"] == [plain_id]
        assert body["job"]["payload"]["document_ids"] == [gold_id]
        assert body["job"]["kind"] == "batch_extract"
    finally:
        dispose_db()


def test_cancel_job_is_sticky(tmp_path: Path):
    _setup_project(tmp_path)
    try:
        job = jobs_mod.create_job(
            kind="batch_extract",
            payload={
                "document_ids": [1, 2],
                "llm_profile_ids": ["p"],
                "items": [
                    {"document_id": 1, "llm_profile_id": "p", "status": "pending"},
                    {"document_id": 2, "llm_profile_id": "p", "status": "running"},
                ],
            },
            enqueue=False,
        )
        client = TestClient(create_app())
        res = client.post(f"/api/evaluation/jobs/{job['id']}/cancel")
        assert res.status_code == 200
        body = res.json()["job"]
        assert body["status"] == "cancelled"
        assert body["message"] == "Отменено"
        assert body["payload"]["items"][0]["status"] == "cancelled"
        assert body["payload"]["items"][1]["status"] == "running"

        jobs_mod._update_job(
            job["id"],
            status="completed",
            message="Пакет завершён",
            progress=1.0,
            finished=True,
        )
        stuck = jobs_mod.get_job(job["id"])
        assert stuck["status"] == "cancelled"
        assert stuck["message"] == "Отменено"

        denied = client.post(f"/api/evaluation/jobs/{job['id']}/cancel")
        assert denied.status_code == 400
        missing = client.post("/api/evaluation/jobs/999999/cancel")
        assert missing.status_code == 404
    finally:
        dispose_db()
