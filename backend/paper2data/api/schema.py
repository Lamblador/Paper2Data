"""API схемы: шаблоны, применение, редактирование типов."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.schema.loader import list_templates, resolve_template
from paper2data.schema import service as schema_service

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class ApplyTemplateBody(BaseModel):
    template_id: str


class EntityTypeBody(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    label_attribute: str | None = None
    attributes: list[dict[str, Any]] | None = None


class AttributeBody(BaseModel):
    id: str
    name: str | None = None
    type: str = "text"
    required: bool = False
    unit: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    llm_hint: str = ""
    default: str | None = None


class RelationTypeBody(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    cardinality: str | None = None
    attributes: list[dict[str, Any]] | None = None
    llm_hint: str | None = None

    model_config = {"populate_by_name": True}


@router.get("/templates")
def api_list_templates() -> dict:
    return {"templates": list_templates()}


@router.get("/templates/{template_id}")
def api_get_template(template_id: str) -> dict:
    try:
        resolved = resolve_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": resolved}


@router.get("/current")
def api_current_schema() -> dict:
    _require_project()
    with session_scope() as session:
        active = schema_service.get_active_schema_version(session)
        if active is None:
            return {"schema": None}
        return {"schema": schema_service.serialize_schema(active)}


@router.post("/apply")
def api_apply_template(body: ApplyTemplateBody) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.apply_template(session, project, body.template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.post("/entity-types")
def api_upsert_entity_type(body: EntityTypeBody) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.upsert_entity_type(
                session, project, body.model_dump(exclude_none=True)
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.delete("/entity-types/{type_id}")
def api_delete_entity_type(type_id: str) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.delete_entity_type(session, project, type_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.post("/entity-types/{entity_type_id}/attributes")
def api_upsert_attribute(entity_type_id: str, body: AttributeBody) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.upsert_attribute(
                session,
                project,
                entity_type_id,
                body.model_dump(),
            )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.delete("/entity-types/{entity_type_id}/attributes/{attr_id}")
def api_delete_attribute(entity_type_id: str, attr_id: str) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.delete_attribute(
                session, project, entity_type_id, attr_id
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.post("/relation-types")
def api_upsert_relation_type(body: RelationTypeBody) -> dict:
    project = _require_project()
    data = body.model_dump(by_alias=True, exclude_none=True)
    try:
        with session_scope() as session:
            schema = schema_service.upsert_relation_type(session, project, data)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}


@router.delete("/relation-types/{type_id}")
def api_delete_relation_type(type_id: str) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            schema = schema_service.delete_relation_type(session, project, type_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema": schema}
