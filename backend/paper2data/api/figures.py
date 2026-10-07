"""API рисунков: галерея, классы, разметка, классификация (M5)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.figures import service as figures_service
from paper2data.figures.embeddings import embedding_status

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class CreateClassBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    description: str = ""


class AssignClassBody(BaseModel):
    class_id: int | None = None


@router.get("/status")
def figures_status() -> dict:
    _require_project()
    return {
        "embedding": embedding_status(),
        "confidence_threshold": figures_service.confidence_threshold(),
        "detection": {
            "method": "embedded_images_and_caption_regions",
            "yolo_doclayout": False,
            "note": (
                "DocLayout/YOLO не используются: извлечение через встроенные "
                "изображения PDF и рендер области над подписью (Fig./Scheme/Table)."
            ),
        },
    }


@router.get("/classes")
def list_classes() -> dict:
    _require_project()
    with session_scope() as session:
        return {"classes": figures_service.list_classes(session)}


@router.post("/classes")
def create_class(body: CreateClassBody) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            cls = figures_service.add_class(
                session, slug=body.slug, name=body.name, description=body.description
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"class": cls}


@router.get("")
def list_figures(
    document_id: int | None = Query(None),
    uncertain_only: bool = Query(False),
    class_id: int | None = Query(None),
) -> dict:
    _require_project()
    with session_scope() as session:
        figures = figures_service.list_figures(
            session,
            document_id=document_id,
            uncertain_only=uncertain_only,
            class_id=class_id,
        )
        return {"figures": figures, "count": len(figures)}


@router.post("/documents/{document_id}/extract")
def extract_figures(document_id: int, auto_classify: bool = Query(True)) -> dict:
    project = _require_project()
    with session_scope() as session:
        try:
            figures = figures_service.extract_and_store_figures(
                session,
                project,
                document_id,
                replace=True,
                auto_classify=auto_classify,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"figures": figures, "count": len(figures), "embedding": embedding_status()}


@router.post("/classify")
def classify_batch(
    document_id: int | None = Query(None),
    only_unlabeled: bool = Query(True),
) -> dict:
    _require_project()
    with session_scope() as session:
        return figures_service.classify_all(
            session, document_id=document_id, only_unlabeled=only_unlabeled
        )


@router.get("/{figure_id}")
def get_figure(figure_id: int) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            fig = figures_service.get_figure(session, figure_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"figure": figures_service.serialize_figure(fig)}


@router.get("/{figure_id}/image")
def get_figure_image(figure_id: int) -> FileResponse:
    project = _require_project()
    with session_scope() as session:
        try:
            fig = figures_service.get_figure(session, figure_id)
            path = figures_service.resolve_figure_image_path(project, fig)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="image/png", filename=path.name)


@router.post("/{figure_id}/assign")
def assign_class(figure_id: int, body: AssignClassBody) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            fig = figures_service.assign_class(session, figure_id, body.class_id, manual=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"figure": fig}


@router.post("/{figure_id}/classify")
def classify_one(figure_id: int) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            fig = figures_service.classify_figure(session, figure_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"figure": fig}


@router.post("/{figure_id}/extract-data")
def extract_data_stub(figure_id: int) -> dict:
    """Заглушка FigureDataExtractor (OCSR / дигитайзер — будущее)."""
    project = _require_project()
    with session_scope() as session:
        try:
            return figures_service.try_extract_data(session, project, figure_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
