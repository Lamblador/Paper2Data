"""API извлечения: рецепты, прогоны, очередь проверки (M3)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.extraction import engine as extraction_engine
from paper2data.extraction import generator as recipe_generator
from paper2data.extraction import recipes as recipe_mod
from paper2data.extraction import review as review_mod
from paper2data.extraction.quotes import verify_quote_in_text
from paper2data.graph import service as graph_service
from paper2data.schema import service as schema_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


def _fail_run(session, exc: Exception) -> None:
    """Сохраняет статус failed и отдаёт текст ошибки в UI вместо необработанного 500."""
    logger.error("Прогон извлечения не завершился: %s", exc)
    try:
        session.commit()
    except Exception:
        session.rollback()
    detail = str(exc).strip() or "Ошибка прогона"
    raise HTTPException(status_code=400, detail=detail[:1500]) from exc


class RecipeSaveBody(BaseModel):
    recipe: dict[str, Any]
    activate: bool = True


class RecipeGenerateBody(BaseModel):
    document_id: int | None = None
    gold_snapshot_id: int | None = None
    intelligence_level: str = "medium"
    recipe_id: str | None = None
    name: str | None = None
    save: bool = True


class PromptPreviewBody(BaseModel):
    document_id: int
    recipe_id: str | None = None
    step_id: str
    run_id: int | None = None


class CreateRunBody(BaseModel):
    document_id: int
    recipe_id: str | None = None
    llm_profile_id: str | None = None
    strategy: str | None = None
    options: dict[str, Any] | None = None


class RunStepBody(BaseModel):
    step_id: str | None = None
    phase: str | None = None
    dry_run: bool = False


class RunPipelineBody(BaseModel):
    stop_after_step: str | None = None


class ReviewActionBody(BaseModel):
    kind: str
    id: int
    payload: dict[str, Any] = Field(default_factory=dict)
    accept: bool = True


class MergeBody(BaseModel):
    keep_id: int
    merge_id: int


class VerifyQuoteBody(BaseModel):
    quote: str
    text: str
    threshold: float = 90


@router.get("/recipes")
def list_recipes() -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        db_items = extraction_engine.list_recipes_db(session)
    bundled = recipe_mod.list_bundled_recipes()
    project_files = recipe_mod.list_project_recipe_files(project.root)
    return {
        "recipes": db_items,
        "bundled": bundled,
        "project_files": project_files,
    }


@router.get("/recipes/bundled/{recipe_id}")
def get_bundled_recipe(recipe_id: str) -> dict[str, Any]:
    project = _require_project()
    try:
        body = recipe_mod.resolve_recipe(recipe_id, project_root=project.root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"recipe": body}


@router.get("/recipes/{recipe_db_id}")
def get_recipe(recipe_db_id: int) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            return {"recipe": extraction_engine.get_recipe_db(session, recipe_db_id)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/recipes")
def save_recipe(body: RecipeSaveBody) -> dict[str, Any]:
    project = _require_project()
    try:
        with session_scope() as session:
            row = extraction_engine.upsert_recipe_db(
                session, project, body.recipe, activate=body.activate
            )
            return {"recipe": row}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recipes/generate")
def generate_recipe(body: RecipeGenerateBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        schema_row = schema_service.get_active_schema_version(session)
        if schema_row is None:
            raise HTTPException(status_code=400, detail="Схема проекта не применена")
        schema = schema_service.schema_dict_from_db(schema_row)
        gold_payload: dict[str, Any] = {}
        if body.gold_snapshot_id is not None:
            try:
                gold_payload = graph_service.get_gold_snapshot(
                    session, body.gold_snapshot_id
                ).get("payload") or {}
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        elif body.document_id is not None:
            golds = graph_service.list_gold_snapshots(session, body.document_id)
            if golds:
                gold_payload = graph_service.get_gold_snapshot(
                    session, golds[0]["id"]
                ).get("payload") or {}
        recipe = recipe_generator.generate_recipe_from_schema_and_gold(
            schema,
            gold_payload=gold_payload or None,
            intelligence_level=body.intelligence_level,
            recipe_id=body.recipe_id,
            name=body.name,
        )
        saved = None
        if body.save:
            saved = extraction_engine.upsert_recipe_db(session, project, recipe)
        return {"recipe": saved or recipe, "generated": recipe}


@router.post("/recipes/preview-prompt")
def preview_prompt(body: PromptPreviewBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            preview = extraction_engine.preview_step_prompt(
                session,
                project,
                document_id=body.document_id,
                recipe_id=body.recipe_id,
                step_id=body.step_id,
                run_id=body.run_id,
            )
            return {"preview": preview}
        except (LookupError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/strategies/default")
def default_strategy(intelligence_level: str = "medium") -> dict[str, str]:
    return {
        "intelligence_level": intelligence_level,
        "strategy": recipe_mod.default_strategy_for_intelligence(intelligence_level),
    }


@router.post("/runs")
def create_run(body: CreateRunBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            run = extraction_engine.create_run(
                session,
                project,
                document_id=body.document_id,
                recipe_id=body.recipe_id,
                llm_profile_id=body.llm_profile_id,
                strategy=body.strategy,
                options=body.options,
            )
            return {"run": run}
        except (LookupError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
def list_runs(document_id: int | None = None) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        return {"runs": extraction_engine.list_runs(session, document_id, project)}


@router.get("/runs/{run_id}")
def get_run(run_id: int) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            return {"run": extraction_engine.get_run(session, run_id, project)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/steps")
def run_step(run_id: int, body: RunStepBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            result = extraction_engine.run_step(
                session,
                project,
                run_id=run_id,
                step_id=body.step_id,
                phase=body.phase,
                dry_run=body.dry_run,
            )
            return result
        except Exception as exc:
            _fail_run(session, exc)


@router.post("/runs/{run_id}/pipeline")
def run_pipeline(run_id: int, body: RunPipelineBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            return extraction_engine.run_pipeline(
                session,
                project,
                run_id=run_id,
                stop_after_step=body.stop_after_step,
            )
        except Exception as exc:
            _fail_run(session, exc)


@router.get("/review/{document_id}")
def review_queue(
    document_id: int,
    run_id: int | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            return review_mod.list_review_queue(
                session,
                document_id,
                run_id=run_id,
                status=status,
                project=project,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/reopen")
def review_reopen(body: ReviewActionBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            item = review_mod.reopen_item(session, kind=body.kind, item_id=body.id)
            return {"item": item}
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            if "locked" in detail.lower():
                detail = (
                    "База занята длинным прогоном LLM. Дождитесь окончания шага "
                    "извлечения и нажмите «Вернуть в проверку» снова."
                )
            raise HTTPException(status_code=400, detail=detail[:800]) from exc


@router.post("/review/accept")
def review_accept(body: ReviewActionBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            item = review_mod.accept_item(session, kind=body.kind, item_id=body.id)
            return {"item": item}
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/reject")
def review_reject(body: ReviewActionBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            item = review_mod.reject_item(session, kind=body.kind, item_id=body.id)
            return {"item": item}
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/edit")
def review_edit(body: ReviewActionBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            item = review_mod.edit_item(
                session,
                kind=body.kind,
                item_id=body.id,
                payload=body.payload,
                accept=body.accept,
            )
            return {"item": item}
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/merge")
def review_merge(body: MergeBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            node = review_mod.merge_nodes(
                session, keep_id=body.keep_id, merge_id=body.merge_id
            )
            return {"node": node}
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/verify-quote")
def verify_quote(body: VerifyQuoteBody) -> dict[str, Any]:
    match = verify_quote_in_text(body.quote, body.text, threshold=body.threshold)
    return {
        "verified": match.verified,
        "score": match.score,
        "matched_text": match.matched_text,
    }
