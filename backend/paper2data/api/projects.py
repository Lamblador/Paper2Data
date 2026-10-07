"""API проектов: создать / открыть / текущий / выбор папки."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.core.project import (
    close_project,
    create_project,
    get_current_project,
    list_recent_projects,
    open_project,
    pick_folder_dialog,
    save_project_settings,
)
from paper2data.db.session import check_db_alive, dispose_db

router = APIRouter()


class PathBody(BaseModel):
    path: str = Field(..., description="Путь к папке проекта")
    name: str | None = Field(None, description="Имя проекта (только при создании)")


class ProjectOut(BaseModel):
    path: str
    name: str
    schema_template: str | None = None
    active_schema: str | None = None
    created_at: str
    updated_at: str
    db_ready: bool
    papers_dir: str
    cache_dir: str
    exports_dir: str
    llm_profiles_count: int


def _serialize(project) -> ProjectOut:
    return ProjectOut(
        path=str(project.root),
        name=project.settings.name,
        schema_template=project.settings.schema_template,
        active_schema=project.settings.active_schema,
        created_at=project.settings.created_at,
        updated_at=project.settings.updated_at,
        db_ready=check_db_alive(),
        papers_dir=str(project.papers_dir),
        cache_dir=str(project.cache_dir),
        exports_dir=str(project.exports_dir),
        llm_profiles_count=len(project.settings.llm_profiles),
    )


@router.get("/current")
def api_current_project() -> dict:
    project = get_current_project()
    if project is None:
        return {"project": None}
    return {"project": _serialize(project)}


@router.get("/recent")
def api_recent_projects() -> dict:
    return {"projects": list_recent_projects()}


@router.post("/pick-folder")
def api_pick_folder() -> dict:
    try:
        selected = pick_folder_dialog("Выберите папку проекта Paper2Data")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Не удалось открыть диалог: {exc}") from exc
    return {"path": selected}


@router.post("/create")
def api_create_project(body: PathBody) -> dict:
    try:
        project = create_project(body.path, name=body.name)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": _serialize(project)}


@router.post("/open")
def api_open_project(body: PathBody) -> dict:
    try:
        project = open_project(body.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": _serialize(project)}


@router.post("/close")
def api_close_project() -> dict:
    close_project()
    dispose_db()
    return {"ok": True}


class RenameBody(BaseModel):
    name: str


@router.patch("/current")
def api_rename_project(body: RenameBody) -> dict:
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    project.settings.name = body.name.strip() or project.settings.name
    save_project_settings(project)
    return {"project": _serialize(project)}


@router.post("/create-with-dialog")
def api_create_with_dialog() -> dict:
    selected = pick_folder_dialog("Выберите пустую папку для нового проекта")
    if not selected:
        return {"cancelled": True, "project": None}
    path = Path(selected)
    try:
        if (path / "project.yaml").exists():
            project = open_project(path)
        else:
            project = create_project(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cancelled": False, "project": _serialize(project)}


@router.post("/open-with-dialog")
def api_open_with_dialog() -> dict:
    selected = pick_folder_dialog("Выберите папку существующего проекта")
    if not selected:
        return {"cancelled": True, "project": None}
    try:
        project = open_project(selected)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cancelled": False, "project": _serialize(project)}
