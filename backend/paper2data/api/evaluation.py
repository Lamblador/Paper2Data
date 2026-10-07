"""API корпуса: оценка, пакет, лидерборд, дубли, экспорт (M4)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.evaluation import duplicates as dup_mod
from paper2data.evaluation import estimate as estimate_mod
from paper2data.evaluation import export_full as export_mod
from paper2data.evaluation import jobs as jobs_mod
from paper2data.evaluation import service as eval_service

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class EstimateBody(BaseModel):
    document_ids: list[int]
    llm_profile_ids: list[str]
    recipe_id: str | None = None


class BatchStartBody(BaseModel):
    document_ids: list[int]
    llm_profile_ids: list[str]
    recipe_id: str | None = None
    strategy: str | None = None
    evaluate: bool = True


class FullExtractStartBody(BaseModel):
    document_ids: list[int]
    llm_profile_id: str
    recipe_id: str | None = None
    strategy: str | None = None
    ingest_missing: bool = True
    reparse: bool = False


class EvaluateBody(BaseModel):
    gold_snapshot_id: int | None = None
    persist: bool = True


class ApplyCanonicalBody(BaseModel):
    node_ids: list[int]
    canonical_id: str


class ExportBody(BaseModel):
    document_ids: list[int] | None = None
    include_sdf: bool = True


@router.post("/estimate")
def api_estimate(body: EstimateBody) -> dict[str, Any]:
    project = _require_project()
    if not body.document_ids or not body.llm_profile_ids:
        raise HTTPException(status_code=400, detail="Укажите document_ids и llm_profile_ids")
    with session_scope() as session:
        try:
            estimate = estimate_mod.estimate_corpus_cost(
                session,
                project,
                document_ids=body.document_ids,
                llm_profile_ids=body.llm_profile_ids,
                recipe_id=body.recipe_id,
            )
            return {"estimate": estimate}
        except (LookupError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch")
def api_batch_start(body: BatchStartBody) -> dict[str, Any]:
    _require_project()
    if not body.document_ids or not body.llm_profile_ids:
        raise HTTPException(status_code=400, detail="Укажите document_ids и llm_profile_ids")

    document_ids = list(body.document_ids)
    skipped_without_gold: list[int] = []
    if body.evaluate:
        with session_scope() as session:
            kept: list[int] = []
            for doc_id in document_ids:
                if eval_service._latest_gold(session, doc_id) is None:
                    skipped_without_gold.append(doc_id)
                else:
                    kept.append(doc_id)
            document_ids = kept
        if not document_ids:
            raise HTTPException(
                status_code=400,
                detail="Нет статей с эталоном",
            )

    job = jobs_mod.create_job(
        kind="batch_extract",
        payload={
            "document_ids": document_ids,
            "llm_profile_ids": body.llm_profile_ids,
            "recipe_id": body.recipe_id,
            "strategy": body.strategy,
            "evaluate": body.evaluate,
            "items": [],
            "cursor": 0,
        },
        enqueue=True,
    )
    return {"job": job, "skipped_without_gold": skipped_without_gold}


@router.post("/full-extract")
def api_full_extract_start(body: FullExtractStartBody) -> dict[str, Any]:
    _require_project()
    if not body.document_ids or not body.llm_profile_id:
        raise HTTPException(
            status_code=400,
            detail="Укажите document_ids и llm_profile_id",
        )
    job = jobs_mod.create_job(
        kind="full_extract",
        payload={
            "document_ids": body.document_ids,
            "llm_profile_id": body.llm_profile_id,
            "recipe_id": body.recipe_id,
            "strategy": body.strategy,
            "ingest_missing": body.ingest_missing,
            "reparse": body.reparse,
            "items": [],
            "cursor": 0,
        },
        enqueue=True,
    )
    return {"job": job}


@router.get("/jobs")
def api_list_jobs(kind: str | None = None, limit: int = 50) -> dict[str, Any]:
    _require_project()
    return {"jobs": jobs_mod.list_jobs(kind=kind, limit=limit)}


@router.get("/jobs/{job_id}")
def api_get_job(job_id: int) -> dict[str, Any]:
    _require_project()
    try:
        return {"job": jobs_mod.get_job(job_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(job_id: int) -> dict[str, Any]:
    _require_project()
    try:
        return {"job": jobs_mod.cancel_job(job_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/resume")
def api_resume_job(job_id: int) -> dict[str, Any]:
    _require_project()
    try:
        job = jobs_mod.get_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job["status"] not in {"failed", "running", "pending"}:
        raise HTTPException(status_code=400, detail=f"Нельзя возобновить статус {job['status']}")
    if job.get("kind") not in {"batch_extract", "full_extract"}:
        raise HTTPException(
            status_code=400,
            detail=f"Возобновление не поддерживается для kind={job.get('kind')}",
        )
    # сбросить failed items
    payload = dict(job.get("payload") or {})
    kind = job.get("kind") or "batch_extract"
    for it in payload.get("items") or []:
        jobs_mod._reset_failed_item(it, kind=kind)
    with session_scope() as session:
        from paper2data.db.models import Job

        row = session.get(Job, job_id)
        if row:
            row.payload_json = json.dumps(payload, ensure_ascii=False)
            row.status = "pending"
            row.error_message = None
            row.message = "Возобновление"
    jobs_mod.enqueue_job(job_id)
    return {"job": jobs_mod.get_job(job_id)}


@router.post("/jobs/resume-failed")
def api_resume_failed() -> dict[str, Any]:
    _require_project()
    ids = jobs_mod.resume_failed_jobs()
    return {"resumed": ids}


@router.get("/jobs/{job_id}/events")
async def api_job_events(job_id: int) -> StreamingResponse:
    """SSE прогресс задачи."""
    _require_project()
    try:
        jobs_mod.get_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_event(data: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, data)

    jobs_mod.subscribe(job_id, on_event)

    async def gen():
        try:
            # начальный снимок
            snap = jobs_mod.get_job(job_id)
            yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
            if snap.get("status") in {"completed", "failed", "cancelled"}:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keepalive + poll
                    snap = jobs_mod.get_job(job_id)
                    yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                    if snap.get("status") in {"completed", "failed", "cancelled"}:
                        return
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("status") in {"completed", "failed", "cancelled"}:
                    return
        finally:
            jobs_mod.unsubscribe(job_id, on_event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/runs/{run_id}/evaluate")
def api_evaluate_run(run_id: int, body: EvaluateBody | None = None) -> dict[str, Any]:
    project = _require_project()
    body = body or EvaluateBody()
    with session_scope() as session:
        try:
            result = eval_service.evaluate_run(
                session,
                project,
                run_id=run_id,
                gold_snapshot_id=body.gold_snapshot_id,
                persist=body.persist,
            )
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evaluations")
def api_list_evaluations(
    document_id: int | None = None,
    llm_profile_id: str | None = None,
) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        return {
            "evaluations": eval_service.list_evaluations(
                session, document_id=document_id, llm_profile_id=llm_profile_id
            )
        }


@router.get("/leaderboard")
def api_leaderboard() -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        return eval_service.leaderboard(session, project)


@router.get("/duplicates")
def api_duplicates(entity_type: str = "Compound", min_score: float = 0.75) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        suggestions = dup_mod.suggest_cross_document_duplicates(
            session, entity_type=entity_type, min_score=min_score
        )
        return {"suggestions": suggestions, "count": len(suggestions)}


@router.post("/duplicates/apply")
def api_apply_canonical(body: ApplyCanonicalBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        updated = dup_mod.apply_canonical_ids(
            session, node_ids=body.node_ids, canonical_id=body.canonical_id
        )
        return {"nodes": updated, "canonical_id": body.canonical_id}


@router.post("/export")
def api_export(body: ExportBody | None = None) -> dict[str, Any]:
    project = _require_project()
    body = body or ExportBody()
    with session_scope() as session:
        result = export_mod.export_full(
            session,
            project,
            document_ids=body.document_ids,
            include_sdf=body.include_sdf,
        )
        return {"export": result}
