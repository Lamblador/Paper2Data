"""API статей: индекс, ingest, структура, PDF, ESI."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from paper2data.core.project import get_current_project
from paper2data.db.models import Document
from paper2data.db.session import session_scope
from paper2data.ingest import service as ingest_service

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class EsiLinkBody(BaseModel):
    url: str = Field(..., min_length=3)


@router.get("")
def list_papers() -> dict:
    _require_project()
    with session_scope() as session:
        docs = session.scalars(
            select(Document)
            .options(
                selectinload(Document.files),
                selectinload(Document.sections),
                selectinload(Document.gold_snapshots),
            )
            .order_by(Document.id)
        ).all()
        return {
            "papers": [ingest_service.serialize_document_brief(d) for d in docs]
        }


@router.post("/index")
def index_papers() -> dict:
    project = _require_project()
    with session_scope() as session:
        docs = ingest_service.index_papers(session, project)
        return {
            "papers": [ingest_service.serialize_document_brief(d) for d in docs],
            "count": len(docs),
        }


@router.post("/upload")
async def upload_paper(file: UploadFile = File(...)) -> dict:
    project = _require_project()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Нет имени файла")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    with session_scope() as session:
        doc = ingest_service.upload_pdf(session, project, file.filename, data)
        session.refresh(doc)
        doc = session.scalar(
            select(Document)
            .where(Document.id == doc.id)
            .options(selectinload(Document.files), selectinload(Document.sections))
        )
        if doc is None:
            raise HTTPException(status_code=500, detail="Документ не найден после загрузки")
        return {"paper": ingest_service.serialize_document_brief(doc)}


@router.post("/{document_id}/ingest")
def ingest_paper(document_id: int) -> dict:
    project = _require_project()
    with session_scope() as session:
        try:
            ingest_service.ingest_document(session, project, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # статус error уже записан
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        structure = ingest_service.get_document_structure(session, document_id)
        return {"paper": structure}


@router.get("/{document_id}")
def get_paper(document_id: int) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            structure = ingest_service.get_document_structure(session, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"paper": structure}


@router.get("/{document_id}/structure")
def get_paper_structure(document_id: int) -> dict:
    return get_paper(document_id)


@router.get("/{document_id}/file")
def get_paper_file(
    document_id: int,
    file_id: int | None = Query(None),
    role: str = Query("main"),
) -> FileResponse:
    project = _require_project()
    with session_scope() as session:
        try:
            path = ingest_service.resolve_pdf_path(
                project, session, document_id, file_id=file_id, role=role
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=path.name,
            content_disposition_type="inline",
        )


@router.post("/{document_id}/esi/attach")
async def attach_esi(document_id: int, file: UploadFile = File(...)) -> dict:
    project = _require_project()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Нет имени файла")
    data = await file.read()
    with session_scope() as session:
        try:
            ingest_service.attach_esi_file(
                session, project, document_id, file.filename, data, ingest=True
            )
            structure = ingest_service.get_document_structure(session, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"paper": structure}


@router.delete("/{document_id}/esi/files/{file_id}")
def delete_esi_file(document_id: int, file_id: int) -> dict:
    project = _require_project()
    with session_scope() as session:
        try:
            ingest_service.detach_esi_file(session, project, document_id, file_id)
            structure = ingest_service.get_document_structure(session, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"paper": structure}


@router.post("/{document_id}/esi/link")
def save_esi_link(document_id: int, body: EsiLinkBody) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            ingest_service.record_esi_link(session, document_id, body.url.strip())
            structure = ingest_service.get_document_structure(session, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"paper": structure}


@router.delete("/{document_id}/esi/link")
def delete_esi_link(document_id: int, body: EsiLinkBody) -> dict:
    _require_project()
    with session_scope() as session:
        try:
            ingest_service.remove_esi_link(session, document_id, body.url.strip())
            structure = ingest_service.get_document_structure(session, document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"paper": structure}
