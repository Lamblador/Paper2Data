"""API чат-ассистента (M6)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from paper2data.assistant import service as assistant_service
from paper2data.assistant.tools import TOOL_DEFINITIONS
from paper2data.core.project import get_current_project
from paper2data.db.session import session_scope
from paper2data.llm import profiles as profiles_svc

router = APIRouter()


def _require_project():
    project = get_current_project()
    if project is None:
        raise HTTPException(status_code=400, detail="Проект не открыт")
    return project


class ChatBody(BaseModel):
    document_id: int
    content: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    llm_profile_id: str | None = None
    max_rounds: int | None = None


class ConfirmBody(BaseModel):
    document_id: int
    mutations: list[dict[str, Any]] = Field(default_factory=list)


class RejectBody(BaseModel):
    document_id: int
    mutation_ids: list[str] = Field(default_factory=list)


@router.get("/tools")
def api_list_tools() -> dict[str, Any]:
    return {"tools": TOOL_DEFINITIONS}


@router.get("/threads/{document_id}")
def api_thread(document_id: int) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        thread = assistant_service.get_thread(session, document_id)
        return {
            "document_id": document_id,
            "events": thread["events"],
            "pending_mutations": thread["pending_mutations"],
        }


@router.post("/chat")
def api_chat(body: ChatBody) -> dict[str, Any]:
    project = _require_project()
    if not (body.content or "").strip() and not body.messages:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    profiles = profiles_svc.list_profiles(project)
    if not profiles:
        raise HTTPException(status_code=400, detail="Нет LLM-профилей в проекте")
    profile_id = body.llm_profile_id or profiles[0]["id"]
    try:
        profile = profiles_svc.get_profile(profile_id, project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with session_scope() as session:
        try:
            chat_kwargs: dict[str, Any] = {
                "document_id": body.document_id,
                "profile": profile,
                "messages": body.messages,
                "content": body.content,
            }
            if body.max_rounds is not None:
                chat_kwargs["max_rounds"] = body.max_rounds
            result = assistant_service.run_chat(session, **chat_kwargs)
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/confirm")
def api_confirm(body: ConfirmBody) -> dict[str, Any]:
    project = _require_project()
    with session_scope() as session:
        try:
            return assistant_service.confirm_mutations(
                session,
                document_id=body.document_id,
                project=project,
                mutations=body.mutations,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reject")
def api_reject(body: RejectBody) -> dict[str, Any]:
    _require_project()
    with session_scope() as session:
        return assistant_service.reject_mutations(
            session,
            document_id=body.document_id,
            mutation_ids=body.mutation_ids,
        )
