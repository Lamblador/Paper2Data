"""API химического обогащения (M6)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.chem import (
    chem_status,
    lookup_doi,
    name_to_structure,
    smiles_to_svg,
    validate_and_draw,
    validate_inchi,
    validate_smiles,
)
from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.graph import service as graph_service

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class ValidateBody(BaseModel):
    smiles: str | None = None
    inchi: str | None = None


class SvgBody(BaseModel):
    smiles: str
    width: int = 280
    height: int = 200


class NameResolveBody(BaseModel):
    name: str = Field(..., min_length=1)
    prefer_opsin: bool = True
    use_pubchem: bool = True


class CrossrefBody(BaseModel):
    doi: str = Field(..., min_length=3)


class ApplyStructureBody(BaseModel):
    """Подтверждение: записать SMILES/InChI в атрибуты узла."""

    node_id: int
    smiles: str | None = None
    inchi: str | None = None
    iupac: str | None = None
    smiles_attr: str = "smiles"
    inchi_attr: str = "inchi"
    iupac_attr: str = "iupac"


class ApplyCrossrefBody(BaseModel):
    node_id: int
    doi: str | None = None
    title: str | None = None
    doi_attr: str = "doi"
    title_attr: str = "title"


@router.get("/status")
def api_chem_status() -> dict[str, Any]:
    return {"status": chem_status()}


@router.post("/validate")
def api_validate(body: ValidateBody) -> dict[str, Any]:
    if body.smiles and not body.inchi:
        return {"result": validate_smiles(body.smiles)}
    if body.inchi and not body.smiles:
        return {"result": validate_inchi(body.inchi)}
    return {"result": validate_and_draw(smiles=body.smiles, inchi=body.inchi)}


@router.post("/svg")
def api_svg(body: SvgBody) -> dict[str, Any]:
    return {"result": smiles_to_svg(body.smiles, width=body.width, height=body.height)}


@router.post("/name-to-structure")
def api_name_to_structure(body: NameResolveBody) -> dict[str, Any]:
    return {
        "result": name_to_structure(
            body.name,
            prefer_opsin=body.prefer_opsin,
            use_pubchem=body.use_pubchem,
        )
    }


@router.post("/crossref")
def api_crossref(body: CrossrefBody) -> dict[str, Any]:
    return {"result": lookup_doi(body.doi)}


@router.post("/apply-structure")
def api_apply_structure(body: ApplyStructureBody) -> dict[str, Any]:
    """После подтверждения пользователем — записать структуру в узел."""
    _require_project()
    with session_scope() as session:
        try:
            node = graph_service.get_node(session, body.node_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        attrs = dict(node.get("attributes") or {})
        if body.smiles is not None:
            attrs[body.smiles_attr] = body.smiles
        if body.inchi is not None:
            attrs[body.inchi_attr] = body.inchi
        if body.iupac is not None:
            attrs[body.iupac_attr] = body.iupac
        updated = graph_service.update_node(session, body.node_id, {"attributes": attrs})
    return {"node": updated, "ok": True}


@router.post("/apply-crossref")
def api_apply_crossref(body: ApplyCrossrefBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        try:
            node = graph_service.get_node(session, body.node_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        attrs = dict(node.get("attributes") or {})
        if body.doi is not None:
            attrs[body.doi_attr] = body.doi
        if body.title is not None:
            attrs[body.title_attr] = body.title
        label = body.title if body.title else None
        payload: dict[str, Any] = {"attributes": attrs}
        if label:
            payload["label"] = label
        updated = graph_service.update_node(session, body.node_id, payload)
    return {"node": updated, "ok": True}
