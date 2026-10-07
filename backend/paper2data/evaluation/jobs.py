"""In-process очередь фоновых задач + SSE-friendly статус."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from paper2data.core.project import get_current_project
from paper2data.db.models import Job, utcnow
from paper2data.db.session import session_scope

logger = logging.getLogger(__name__)

_queue: list[int] = []
_queue_lock = threading.Lock()
_worker_started = False
_worker_lock = threading.Lock()
_listeners: dict[int, list[Callable[[dict[str, Any]], None]]] = {}
_listeners_lock = threading.Lock()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def serialize_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "payload": _loads(job.payload_json, {}),
        "progress": job.progress,
        "message": job.message,
        "result": _loads(job.result_json, {}),
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def subscribe(job_id: int, callback: Callable[[dict[str, Any]], None]) -> None:
    with _listeners_lock:
        _listeners.setdefault(job_id, []).append(callback)


def unsubscribe(job_id: int, callback: Callable[[dict[str, Any]], None]) -> None:
    with _listeners_lock:
        cbs = _listeners.get(job_id) or []
        if callback in cbs:
            cbs.remove(callback)
        if not cbs and job_id in _listeners:
            del _listeners[job_id]


def _notify(job_dict: dict[str, Any]) -> None:
    jid = job_dict.get("id")
    if jid is None:
        return
    with _listeners_lock:
        cbs = list(_listeners.get(int(jid), []))
    for cb in cbs:
        try:
            cb(job_dict)
        except Exception:  # noqa: BLE001
            logger.exception("job listener error")


def _update_job(
    job_id: int,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> dict[str, Any]:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError(f"Job {job_id} не найден")
        # Отмена необратима: воркер не должен вернуть задачу в running/completed.
        if job.status == "cancelled" and status != "cancelled":
            status = None
            message = None
            result = None
            finished = False
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = float(progress)
        if message is not None:
            job.message = message
        if payload is not None:
            job.payload_json = _dumps(payload)
        if result is not None:
            job.result_json = _dumps(result)
        if error_message is not None:
            job.error_message = error_message
        if started and job.started_at is None:
            job.started_at = utcnow()
        if finished:
            job.finished_at = utcnow()
        job.updated_at = utcnow()
        session.flush()
        data = serialize_job(job)
    _notify(data)
    return data


def create_job(
    *,
    kind: str,
    payload: dict[str, Any],
    enqueue: bool = True,
) -> dict[str, Any]:
    with session_scope() as session:
        job = Job(
            kind=kind,
            status="pending",
            payload_json=_dumps(payload),
            progress=0.0,
            message="Создано",
            result_json="{}",
        )
        session.add(job)
        session.flush()
        data = serialize_job(job)
        job_id = job.id
    if enqueue:
        enqueue_job(job_id)
    return data


def enqueue_job(job_id: int) -> None:
    with _queue_lock:
        if job_id not in _queue:
            _queue.append(job_id)
    _ensure_worker()
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job and job.status in {"pending", "failed"}:
            job.status = "queued"
            job.message = "В очереди"
            job.error_message = None
            session.flush()
            data = serialize_job(job)
        else:
            data = serialize_job(job) if job else {"id": job_id}
    _notify(data)


def _reset_failed_item(item: dict[str, Any], *, kind: str) -> None:
    """Сбросить failed-элемент для повторного прогона."""
    if kind == "full_extract":
        if item.get("stage") != "failed":
            return
        item["stage"] = "pending"
        item["error"] = None
        item["run_id"] = None
        item["nodes"] = 0
        item["edges"] = 0
        item["tokens"] = 0
        item["steps"] = []
        return
    if item.get("status") == "failed":
        item["status"] = "pending"
        item["error"] = None


def resume_failed_jobs() -> list[int]:
    """Вернуть в очередь failed/interrupted batch / full_extract jobs."""
    from sqlalchemy import select

    resumed: list[int] = []
    with session_scope() as session:
        rows = session.scalars(
            select(Job).where(Job.status.in_(["failed", "running"]))
        ).all()
        for job in rows:
            if job.kind not in {"batch_extract", "full_extract"}:
                continue
            payload = _loads(job.payload_json, {})
            items = payload.get("items") or []
            if job.kind == "full_extract":
                needs = (not items) or any(
                    it.get("stage") != "done" for it in items
                )
            else:
                needs = (not items) or any(
                    it.get("status") in {"pending", "running", "failed"} for it in items
                )
            if not needs:
                continue
            for it in items:
                _reset_failed_item(it, kind=job.kind)
            job.payload_json = _dumps(payload)
            job.status = "pending"
            job.message = "Возобновление после сбоя"
            job.error_message = None
            session.flush()
            resumed.append(job.id)
    for jid in resumed:
        enqueue_job(jid)
    return resumed


_CANCELLABLE_STATUSES = {"pending", "queued", "running"}


def _mark_unstarted_cancelled(payload: dict[str, Any], *, kind: str) -> None:
    """Пометить ещё не начатые элементы отменёнными. Текущий шаг не трогаем."""
    for it in payload.get("items") or []:
        if kind == "full_extract":
            if (it.get("stage") or "pending") == "pending":
                it["stage"] = "cancelled"
                it["error"] = None
        elif it.get("status") in {None, "pending"}:
            it["status"] = "cancelled"
            it["error"] = None


def _abort_if_cancelled(job_id: int, payload: dict[str, Any], *, kind: str) -> bool:
    with session_scope() as session:
        job = session.get(Job, job_id)
        cancelled = job is not None and job.status == "cancelled"
    if not cancelled:
        return False
    _mark_unstarted_cancelled(payload, kind=kind)
    _update_job(job_id, payload=payload)
    return True


def cancel_job(job_id: int) -> dict[str, Any]:
    """Остановить пакетный или рабочий прогон.

    Уже идущий вызов модели дорабатывает текущую статью; остальные не стартуют.
    """
    with _queue_lock:
        if job_id in _queue:
            _queue.remove(job_id)
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError(f"Job {job_id} не найден")
        if job.status not in _CANCELLABLE_STATUSES:
            raise ValueError(f"Нельзя отменить статус {job.status}")
        payload = _loads(job.payload_json, {})
        _mark_unstarted_cancelled(payload, kind=job.kind)
        job.payload_json = _dumps(payload)
        session.flush()
    return _update_job(
        job_id,
        status="cancelled",
        message="Отменено",
        payload=payload,
        finished=True,
    )


def get_job(job_id: int) -> dict[str, Any]:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError(f"Job {job_id} не найден")
        return serialize_job(job)


def list_jobs(*, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    from sqlalchemy import select

    with session_scope() as session:
        stmt = select(Job).order_by(Job.id.desc()).limit(limit)
        if kind:
            stmt = stmt.where(Job.kind == kind)
        return [serialize_job(j) for j in session.scalars(stmt).all()]


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, name="paper2data-jobs", daemon=True)
        t.start()
        _worker_started = True


def _worker_loop() -> None:
    while True:
        job_id: int | None = None
        with _queue_lock:
            if _queue:
                job_id = _queue.pop(0)
        if job_id is None:
            time.sleep(0.4)
            continue
        try:
            _run_job(job_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("job %s failed", job_id)
            try:
                _update_job(
                    job_id,
                    status="failed",
                    message="Ошибка",
                    error_message=str(exc),
                    finished=True,
                )
            except Exception:  # noqa: BLE001
                pass


def _run_job(job_id: int) -> None:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        kind = job.kind
        payload = _loads(job.payload_json, {})
        if job.status == "cancelled":
            return

    _update_job(
        job_id,
        status="running",
        progress=0.0,
        message="Запуск",
        started=True,
    )

    if kind == "batch_extract":
        _run_batch_extract(job_id, payload)
    elif kind == "full_extract":
        _run_full_extract(job_id, payload)
    else:
        _update_job(
            job_id,
            status="failed",
            error_message=f"Неизвестный kind: {kind}",
            finished=True,
        )


def _doc_has_text(session, document_id: int) -> bool:
    from paper2data.db.models import Block, Document, Section
    from sqlalchemy import func, select

    doc = session.get(Document, document_id)
    if doc is None:
        return False
    n_sec = session.scalar(
        select(func.count()).select_from(Section).where(Section.document_id == document_id)
    ) or 0
    if n_sec > 0:
        return True
    n_blk = session.scalar(
        select(func.count()).select_from(Block).where(Block.document_id == document_id)
    ) or 0
    return n_blk > 0


def _run_batch_extract(job_id: int, payload: dict[str, Any]) -> None:
    from paper2data.db.models import Document, GoldSnapshot
    from paper2data.extraction import engine as extraction_engine
    from paper2data.evaluation import service as eval_service
    from sqlalchemy import select

    project = get_current_project()
    if project is None:
        _update_job(
            job_id,
            status="failed",
            error_message="Проект не открыт",
            finished=True,
        )
        return

    document_ids = list(payload.get("document_ids") or [])
    profile_ids = list(payload.get("llm_profile_ids") or [])
    recipe_id = payload.get("recipe_id")
    strategy = payload.get("strategy")
    evaluate = bool(payload.get("evaluate", True))

    items = payload.get("items")
    if not items:
        items = [
            {
                "document_id": d,
                "llm_profile_id": p,
                "status": "pending",
                "run_id": None,
                "evaluation_id": None,
                "error": None,
            }
            for d in document_ids
            for p in profile_ids
        ]
        payload["items"] = items

    total = len(items) or 1
    done = sum(1 for it in items if it.get("status") == "done")
    failed = sum(1 for it in items if it.get("status") == "failed")

    for idx, item in enumerate(items):
        if item.get("status") in {"done", "cancelled"}:
            continue
        # проверка отмены
        if _abort_if_cancelled(job_id, payload, kind="batch_extract"):
            return

        item["status"] = "running"
        payload["cursor"] = idx
        _update_job(
            job_id,
            progress=done / total,
            message=f"Документ {item['document_id']} / {item['llm_profile_id']}",
            payload=payload,
        )
        try:
            with session_scope() as session:
                doc = session.get(Document, int(item["document_id"]))
                if doc is None:
                    raise LookupError(f"Документ {item['document_id']} не найден")
                has_text = _doc_has_text(session, int(item["document_id"]))
                has_gold = session.scalars(
                    select(GoldSnapshot.id)
                    .where(GoldSnapshot.document_id == int(item["document_id"]))
                    .limit(1)
                ).first() is not None

            if not has_text:
                item["status"] = "failed"
                item["error"] = "Нет текста (документ не разобран)"
                failed += 1
                payload["items"] = items
                _update_job(
                    job_id,
                    progress=(done + failed) / total,
                    message=f"Пропуск {item['document_id']}: нет текста",
                    payload=payload,
                )
                continue

            # Статья с эталоном → слепой прогон (эталон не в промпте/дедупе)
            run_options: dict[str, Any] = {}
            if has_gold or evaluate:
                run_options["blind"] = True

            with session_scope() as session:
                run = extraction_engine.create_run(
                    session,
                    project,
                    document_id=int(item["document_id"]),
                    recipe_id=recipe_id,
                    llm_profile_id=item["llm_profile_id"],
                    strategy=strategy,
                    options=run_options or None,
                )
                run_id = int(run["id"])
                extraction_engine.run_pipeline(
                    session,
                    project,
                    run_id=run_id,
                    ignore_human_review=True,
                )
                item["run_id"] = run_id
                if evaluate or has_gold:
                    try:
                        ev = eval_service.evaluate_run(
                            session, project, run_id=run_id, persist=True
                        )
                        item["evaluation_id"] = ev.get("id")
                        item["f1"] = ev.get("f1")
                        item["precision"] = ev.get("precision")
                        item["recall"] = ev.get("recall")
                    except LookupError as exc:
                        item["eval_error"] = str(exc)
            item["status"] = "done"
            item["error"] = None
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "batch_extract doc %s / %s failed",
                item.get("document_id"),
                item.get("llm_profile_id"),
            )
            item["status"] = "failed"
            item["error"] = str(exc)
            failed += 1
            payload["items"] = items
            _update_job(
                job_id,
                progress=(done + failed) / total,
                message=(
                    f"Ошибка документа {item['document_id']}; "
                    f"готово {done}/{total}, ошибок: {failed}"
                ),
                payload=payload,
            )
            continue

        payload["items"] = items
        _update_job(
            job_id,
            progress=(done + failed) / total,
            message=f"Готово {done}/{total}"
            + (f", ошибок: {failed}" if failed else ""),
            payload=payload,
        )

    if _abort_if_cancelled(job_id, payload, kind="batch_extract"):
        return

    result = {
        "done": done,
        "failed": failed,
        "total": total,
        "items": items,
    }
    msg = f"Пакет завершён: {done}/{total}"
    if failed:
        msg += f", ошибок: {failed}"
    _update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=msg,
        payload=payload,
        result=result,
        finished=True,
    )


_PHASE_LABELS_RU = {
    "entities": "сущности",
    "relations": "связи",
}


def _full_extract_stage_plan(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """План микростадий: ingest + шаги pipeline (с фазами entities_first).

    OLED-стек не дробим на entities/relations: добор слоёв и HAS_LAYER
    должны идти в одном вызове run_step.
    """
    from paper2data.extraction.device_stack import is_device_stack_step

    plan: list[dict[str, Any]] = [
        {"stage": "ingest", "step_id": None, "phase": None, "label": "разбор"},
    ]
    pipeline = list(recipe.get("pipeline") or [])
    steps_by_id = {s.get("id"): s for s in (recipe.get("steps") or []) if s.get("id")}
    for sid in pipeline:
        step = steps_by_id.get(sid) or {"id": sid}
        if is_device_stack_step(step):
            label = str(step.get("name") or sid)
            plan.append(
                {
                    "stage": sid,
                    "step_id": sid,
                    "phase": None,
                    "label": label,
                }
            )
            continue
        if step.get("strategy") == "entities_first" and step.get("phases"):
            for ph in step["phases"]:
                pname = str(ph.get("name") or "entities")
                plan.append(
                    {
                        "stage": f"{sid}:{pname}",
                        "step_id": sid,
                        "phase": pname,
                        "label": _PHASE_LABELS_RU.get(pname, pname),
                    }
                )
        else:
            label = str(step.get("name") or sid)
            if sid == "resolve_abbreviations" or step.get("output_key") == "abbreviation_map":
                label = "словарь"
            plan.append(
                {
                    "stage": sid,
                    "step_id": sid,
                    "phase": None,
                    "label": label,
                }
            )
    return plan


def _run_full_extract(job_id: int, payload: dict[str, Any]) -> None:
    from paper2data.db.models import Document
    from paper2data.extraction import engine as extraction_engine
    from paper2data.ingest import service as ingest_service
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    project = get_current_project()
    if project is None:
        _update_job(
            job_id,
            status="failed",
            error_message="Проект не открыт",
            finished=True,
        )
        return

    document_ids = list(payload.get("document_ids") or [])
    llm_profile_id = payload.get("llm_profile_id")
    if not llm_profile_id:
        _update_job(
            job_id,
            status="failed",
            error_message="Не указан llm_profile_id",
            finished=True,
        )
        return
    recipe_id = payload.get("recipe_id")
    strategy = payload.get("strategy")
    ingest_missing = bool(payload.get("ingest_missing", True))
    reparse = bool(payload.get("reparse", False))

    # план стадий по активному рецепту
    with session_scope() as session:
        recipe = extraction_engine.get_active_recipe_body(session, project, recipe_id)
    stage_plan = _full_extract_stage_plan(recipe)
    n_micro = max(len(stage_plan), 1)

    items = payload.get("items")
    if not items:
        items = [
            {
                "document_id": d,
                "stage": "pending",
                "run_id": None,
                "nodes": 0,
                "edges": 0,
                "tokens": 0,
                "error": None,
                "steps": [],
            }
            for d in document_ids
        ]
        payload["items"] = items

    total = len(items) or 1

    def _counts() -> tuple[int, int]:
        d = sum(1 for it in items if it.get("stage") == "done")
        f = sum(1 for it in items if it.get("stage") == "failed")
        return d, f

    for idx, item in enumerate(items):
        if item.get("stage") in {"done", "failed", "cancelled"}:
            continue

        if _abort_if_cancelled(job_id, payload, kind="full_extract"):
            return

        payload["cursor"] = idx
        doc_id = int(item["document_id"])

        try:
            # --- ingest ---
            need_ingest = False
            with session_scope() as session:
                doc = session.scalar(
                    select(Document)
                    .where(Document.id == doc_id)
                    .options(
                        selectinload(Document.sections),
                        selectinload(Document.blocks),
                    )
                )
                if doc is None:
                    raise LookupError(f"Документ {doc_id} не найден")
                no_sections = not (doc.sections or [])
                need_ingest = bool(
                    reparse
                    or (
                        ingest_missing
                        and (no_sections or doc.status in {"indexed", "error"})
                    )
                )

            if need_ingest:
                item["stage"] = "ingest"
                payload["items"] = items
                _update_job(
                    job_id,
                    progress=idx / total,
                    message=f"Статья {doc_id}: разбор текста",
                    payload=payload,
                )
                with session_scope() as session:
                    ingest_service.ingest_document(session, project, doc_id)

            with session_scope() as session:
                if not _doc_has_text(session, doc_id):
                    raise RuntimeError("Нет текста после разбора")

            # --- create run (или продолжить существующий) ---
            run_id = item.get("run_id")
            if not run_id:
                with session_scope() as session:
                    from paper2data.db.models import GoldSnapshot

                    has_gold = session.scalars(
                        select(GoldSnapshot.id)
                        .where(GoldSnapshot.document_id == doc_id)
                        .limit(1)
                    ).first() is not None
                    run_options = {"blind": True} if has_gold else None
                    run = extraction_engine.create_run(
                        session,
                        project,
                        document_id=doc_id,
                        recipe_id=recipe_id,
                        llm_profile_id=str(llm_profile_id),
                        strategy=strategy,
                        options=run_options,
                    )
                    run_id = int(run["id"])
                item["run_id"] = run_id
                item["steps"] = []
                item["nodes"] = 0
                item["edges"] = 0
                item["tokens"] = 0
                item["blind"] = bool(run_options)

            # с какой микростадии продолжить
            start_i = 0
            cur_stage = item.get("stage") or "pending"
            recorded = list(item.get("steps") or [])
            if recorded:
                last = recorded[-1]
                last_stage = (
                    f"{last['step_id']}:{last['phase']}"
                    if last.get("phase")
                    else str(last.get("step_id") or "")
                )
                for i, st in enumerate(stage_plan):
                    if st["stage"] == last_stage:
                        start_i = i + 1
                        break
            elif cur_stage not in {"pending", "ingest", None}:
                for i, st in enumerate(stage_plan):
                    if st["stage"] == cur_stage:
                        start_i = i
                        break
            # ingest уже сделан — начинаем с первого шага рецепта
            if start_i == 0 and stage_plan and stage_plan[0]["stage"] == "ingest":
                start_i = 1

            for si, st in enumerate(stage_plan):
                if si < start_i:
                    continue
                if st["stage"] == "ingest":
                    continue

                item["stage"] = st["stage"]
                stage_frac = (si + 1) / n_micro
                progress = (idx + stage_frac) / total
                step_ord = max(si, 1)
                recipe_steps = max(n_micro - 1, 1)
                payload["items"] = items
                _update_job(
                    job_id,
                    progress=min(progress, 0.99),
                    message=(
                        f"Статья {doc_id}: {st['label']} "
                        f"({step_ord}/{recipe_steps})"
                    ),
                    payload=payload,
                )

                with session_scope() as session:
                    step_result = extraction_engine.run_step(
                        session,
                        project,
                        run_id=int(run_id),
                        step_id=st["step_id"],
                        phase=st["phase"],
                    )
                    n_nodes = len(step_result.get("created_nodes") or [])
                    n_edges = len(step_result.get("created_edges") or [])
                    run_stats = (step_result.get("run") or {}).get("stats") or {}
                    tokens = int(run_stats.get("tokens") or 0)

                item["nodes"] = int(item.get("nodes") or 0) + n_nodes
                item["edges"] = int(item.get("edges") or 0) + n_edges
                item["tokens"] = tokens
                if "incomplete_device_stacks" in run_stats:
                    item["incomplete_device_stacks"] = run_stats.get(
                        "incomplete_device_stacks"
                    )
                    item["stack_warning"] = run_stats.get(
                        "incomplete_device_stacks_summary"
                    ) or None
                steps_list = list(item.get("steps") or [])
                steps_list.append(
                    {
                        "step_id": st["step_id"],
                        "phase": st["phase"],
                        "nodes": n_nodes,
                        "edges": n_edges,
                    }
                )
                item["steps"] = steps_list
                payload["items"] = items
                _update_job(job_id, payload=payload)

            item["stage"] = "done"
            item["error"] = None
            if item.get("blind") or item.get("run_id"):
                try:
                    with session_scope() as session:
                        from paper2data.db.models import GoldSnapshot
                        from paper2data.evaluation import service as eval_service

                        has_gold = session.scalars(
                            select(GoldSnapshot.id)
                            .where(GoldSnapshot.document_id == doc_id)
                            .limit(1)
                        ).first() is not None
                        if has_gold and item.get("run_id"):
                            ev = eval_service.evaluate_run(
                                session,
                                project,
                                run_id=int(item["run_id"]),
                                persist=True,
                            )
                            item["evaluation_id"] = ev.get("id")
                            item["f1"] = ev.get("f1")
                except LookupError:
                    pass
            done_n, failed_n = _counts()
            payload["items"] = items
            _update_job(
                job_id,
                progress=(idx + 1) / total,
                message=f"Готово {done_n}/{total}"
                + (f", ошибок: {failed_n}" if failed_n else ""),
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("full_extract doc %s failed", doc_id)
            item["stage"] = "failed"
            item["error"] = str(exc)
            done_n, failed_n = _counts()
            payload["items"] = items
            _update_job(
                job_id,
                progress=(idx + 1) / total,
                message=(
                    f"Ошибка статьи {doc_id}; готово {done_n}/{total}, "
                    f"ошибок: {failed_n}"
                ),
                payload=payload,
            )
            continue

    if _abort_if_cancelled(job_id, payload, kind="full_extract"):
        return

    done_n, failed_n = _counts()
    result = {
        "done": done_n,
        "failed": failed_n,
        "total": total,
        "items": items,
    }
    msg = f"Готово {done_n}/{total}"
    if failed_n:
        msg += f", ошибок: {failed_n}"
    _update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=msg,
        payload=payload,
        result=result,
        finished=True,
    )
