"""API LLM-профилей."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.core.project import get_current_project
from paper2data.llm import profiles as profiles_svc
from paper2data.llm.client import test_connection

router = APIRouter()


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1)
    base_url: str = Field(default="https://api.openai.com/v1")
    model: str = Field(..., min_length=1)
    api_key: str | None = None
    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    context_size: int = Field(default=128000, ge=1)
    intelligence_level: str = "medium"
    supports_json_mode: bool = True


class ProfileUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    price_in_per_1m: float | None = None
    price_out_per_1m: float | None = None
    context_size: int | None = Field(default=None, ge=1)
    intelligence_level: str | None = None
    supports_json_mode: bool | None = None


def _require_open_project() -> None:
    if get_current_project() is None:
        raise HTTPException(status_code=400, detail="Сначала откройте проект")


@router.get("/profiles")
def api_list_profiles() -> dict:
    _require_open_project()
    return {"profiles": profiles_svc.list_profiles()}


@router.post("/profiles")
def api_add_profile(body: ProfileCreate) -> dict:
    _require_open_project()
    profile = profiles_svc.add_profile(
        name=body.name,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
        price_in_per_1m=body.price_in_per_1m,
        price_out_per_1m=body.price_out_per_1m,
        context_size=body.context_size,
        intelligence_level=body.intelligence_level,
        supports_json_mode=body.supports_json_mode,
    )
    items = profiles_svc.list_profiles()
    created = next((p for p in items if p["id"] == profile.id), None)
    if created is None:
        raise HTTPException(status_code=404, detail=f"Профиль не найден: {profile.id}")
    return {"profile": created}


@router.patch("/profiles/{profile_id}")
def api_update_profile(profile_id: str, body: ProfileUpdate) -> dict:
    _require_open_project()
    try:
        profiles_svc.update_profile(profile_id, **body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = profiles_svc.list_profiles()
    updated = next((p for p in items if p["id"] == profile_id), None)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Профиль не найден: {profile_id}")
    return {"profile": updated}


@router.delete("/profiles/{profile_id}")
def api_delete_profile(profile_id: str) -> dict:
    _require_open_project()
    try:
        profiles_svc.delete_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/profiles/{profile_id}/test")
def api_test_profile(profile_id: str) -> dict:
    _require_open_project()
    try:
        profile = profiles_svc.get_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = test_connection(profile)
    return result
