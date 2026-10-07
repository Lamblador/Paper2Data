"""API графа: документы (stub), узлы, рёбра, evidence, эталон, экспорт."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.graph import service as graph_service

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class DocumentCreate(BaseModel):
    title: str = "Без названия"
    doi: str | None = None
    source_path: str | None = None


class EvidenceIn(BaseModel):
    block_id: int | None = None
    quote: str = ""
    page: int | None = None
    bbox: list[float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    created_by: str = "human"
    verified: bool = False


class NodeCreate(BaseModel):
    entity_type: str | None = None
    entity_type_id: int | None = None
    label: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str = "manual"
    canonical_id: str | None = None
    pos_x: float = 0
    pos_y: float = 0
    evidence: EvidenceIn | None = None


class NodeUpdate(BaseModel):
    label: str | None = None
    attributes: dict[str, Any] | None = None
    status: str | None = None
    canonical_id: str | None = None
    pos_x: float | None = None
    pos_y: float | None = None


class EdgeCreate(BaseModel):
    relation_type: str | None = None
    relation_type_id: int | None = None
    source_node_id: int
    target_node_id: int
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str = "manual"
    evidence: EvidenceIn | None = None


class EdgeUpdate(BaseModel):
    attributes: dict[str, Any] | None = None
    status: str | None = None


class EvidenceCreate(BaseModel):
    target_kind: str = "node"
    node_id: int | None = None
    edge_id: int | None = None
    attribute_key: str | None = None
    block_id: int | None = None
    quote: str = ""
    page: int | None = None
    bbox: list[float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    created_by: str = "human"
    verified: bool = False


class GoldBody(BaseModel):
    label: str = "gold"
    only_accepted: bool = True


# ---- Documents (минимально для разметки до готовности M1) ----


@router.get("/documents")
def api_list_documents() -> dict:
    _require_project()
    with session_scope() as session:
        return {"documents": graph_service.list_documents(session)}


@router.post("/documents")
def api_create_document(body: DocumentCreate) -> dict:
    _require_project()
    with session_scope() as session:
        doc = graph_service.create_document(
            session, title=body.title, doi=body.doi, source_path=body.source_path
        )
    return {"document": doc}


@router.get("/documents/{document_id}")
def api_get_document(document_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            docs = graph_service.list_documents(session)
            doc = next((d for d in docs if d["id"] == document_id), None)
            if doc is None:
                raise LookupError(f"Документ не найден: {document_id}")
            graph = graph_service.get_graph(session, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"document": doc, "graph": graph}


# ---- Graph ----


@router.get("/documents/{document_id}/graph")
def api_get_graph(document_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            return graph_service.get_graph(session, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/{document_id}/nodes")
def api_list_nodes(document_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            return {"nodes": graph_service.list_nodes(session, document_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/nodes")
def api_create_node(document_id: int, body: NodeCreate) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            node = graph_service.create_node(
                session,
                document_id,
                body.model_dump(exclude_none=True),
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"node": node}


@router.patch("/nodes/{node_id}")
def api_update_node(node_id: int, body: NodeUpdate) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            node = graph_service.update_node(
                session, node_id, body.model_dump(exclude_none=True)
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"node": node}


@router.delete("/nodes/{node_id}")
def api_delete_node(node_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            graph_service.delete_node(session, node_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/documents/{document_id}/edges")
def api_list_edges(document_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            return {"edges": graph_service.list_edges(session, document_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/edges")
def api_create_edge(document_id: int, body: EdgeCreate) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            edge = graph_service.create_edge(
                session,
                document_id,
                body.model_dump(exclude_none=True),
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"edge": edge}


@router.patch("/edges/{edge_id}")
def api_update_edge(edge_id: int, body: EdgeUpdate) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            edge = graph_service.update_edge(
                session, edge_id, body.model_dump(exclude_none=True)
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"edge": edge}


@router.delete("/edges/{edge_id}")
def api_delete_edge(edge_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            graph_service.delete_edge(session, edge_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/evidences")
def api_create_evidence(body: EvidenceCreate) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            ev = graph_service.create_evidence(session, body.model_dump(exclude_none=True))
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"evidence": ev}


@router.delete("/evidences/{evidence_id}")
def api_delete_evidence(evidence_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            graph_service.delete_evidence(session, evidence_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/documents/{document_id}/gold")
def api_save_gold(document_id: int, body: GoldBody | None = None) -> dict:
    _require_project()
    body = body or GoldBody()
    try:
        with session_scope() as session:
            snap = graph_service.save_gold_snapshot(
                session,
                document_id,
                label=body.label,
                only_accepted=body.only_accepted,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"snapshot": snap}


@router.get("/documents/{document_id}/gold")
def api_list_gold(document_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            return {"snapshots": graph_service.list_gold_snapshots(session, document_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/gold/{snapshot_id}")
def api_get_gold(snapshot_id: int) -> dict:
    _require_project()
    try:
        with session_scope() as session:
            return {"snapshot": graph_service.get_gold_snapshot(session, snapshot_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/export")
def api_export(document_id: int) -> dict:
    project = _require_project()
    try:
        with session_scope() as session:
            result = graph_service.export_document_graph(session, project, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"export": result}
