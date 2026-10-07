"""Чат-ассистент с tool-calling над графом статьи."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paper2data.assistant.tools import TOOL_DEFINITIONS, apply_mutation, execute_tool
from paper2data.core.project import LlmProfileConfig, ProjectState
from paper2data.db.models import AssistantThread
from paper2data.llm.client import chat_completion

SYSTEM_PROMPT = """Ты помощник разметки научных статей в Paper2Data.
Отвечай по-русски, кратко и по делу.
У тебя есть инструменты для чтения графа и текста статьи, а также для предложений изменений.
Мутирующие действия (create_node, update_attributes, add_evidence, run_extraction_step)
только предлагаются — пользователь подтвердит их в UI. Не утверждай, что данные уже записаны.

Правила извлечения:
1. Перед create_node обязательно найди опору в тексте: search_document или get_block_text.
2. В create_node всегда передавай quote — дословную цитату из статьи — и block_id найденного блока.
3. Без quote создавать сущность нельзя. Не выдумывай факты вне текста.
4. Если нужно создать сущность или обновить атрибуты — вызывай соответствующий инструмент.
"""

_TOOL_TITLES = {
    "list_entities": "Список сущностей",
    "get_block_text": "Текст блока",
    "search_document": "Поиск по статье",
    "create_node": "Создать узел",
    "update_attributes": "Обновить атрибуты",
    "add_evidence": "Добавить цитату",
    "run_extraction_step": "Шаг извлечения",
}


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _event(kind: str, content: str, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "kind": kind,
        "content": content[:4000],
    }
    item.update(extra)
    return item


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def describe_tool(name: str, arguments: Any, result: dict[str, Any]) -> str:
    """Короткое описание шага для журнала чата."""
    args = _parse_args(arguments)
    title = _TOOL_TITLES.get(name, name or "инструмент")
    if result.get("error") and not result.get("ok", True):
        return f"{title}: {result['error']}"
    if name == "list_entities":
        count = int(result.get("count") or 0)
        entities = result.get("entities") or []
        preview = ", ".join(
            f"{e.get('entity_type') or '?'} {e.get('label') or ('#' + str(e.get('id')))}"
            for e in entities[:6]
        )
        tail = f" ({preview})" if preview else ""
        if count > 6:
            tail += f" и ещё {count - 6}"
        return f"Посмотрел граф: {count} сущностей{tail}"
    if name == "get_block_text":
        text = str(result.get("text") or "").replace("\n", " ").strip()
        snippet = text[:160] + ("…" if len(text) > 160 else "")
        return (
            f"Прочитал блок #{result.get('block_id')} "
            f"(стр. {result.get('page')}): {snippet or 'пусто'}"
        )
    if name == "search_document":
        query = result.get("query") or args.get("query") or ""
        hits = result.get("hits") or []
        lines = [f"Искал в статье «{query}» — совпадений: {result.get('count', len(hits))}"]
        for hit in hits[:3]:
            snippet = str(hit.get("snippet") or "").replace("\n", " ").strip()
            lines.append(
                f"стр. {hit.get('page')}, блок #{hit.get('block_id')}: {snippet[:120]}"
            )
        return "\n".join(lines)
    proposal = result.get("proposal") if isinstance(result.get("proposal"), dict) else None
    if proposal and proposal.get("summary"):
        return f"Предложил: {proposal['summary']}"
    if name in _TOOL_TITLES and args:
        return f"{title}: {json.dumps(args, ensure_ascii=False)[:240]}"
    return title


def get_thread(session: Session, document_id: int) -> dict[str, Any]:
    row = session.scalar(
        select(AssistantThread).where(AssistantThread.document_id == document_id)
    )
    if row is None:
        return {
            "document_id": document_id,
            "messages": [],
            "events": [],
            "pending_mutations": [],
        }
    return {
        "document_id": document_id,
        "messages": _loads(row.messages_json, []),
        "events": _loads(row.events_json, []),
        "pending_mutations": _loads(row.pending_json, []),
    }


def save_thread(
    session: Session,
    document_id: int,
    *,
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    pending: list[dict[str, Any]],
) -> dict[str, Any]:
    row = session.scalar(
        select(AssistantThread).where(AssistantThread.document_id == document_id)
    )
    if row is None:
        row = AssistantThread(document_id=document_id)
        session.add(row)
    row.messages_json = _dumps(messages)
    row.events_json = _dumps(events)
    row.pending_json = _dumps(pending)
    session.flush()
    return get_thread(session, document_id)


def _public_thread(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": thread["document_id"],
        "events": thread["events"],
        "pending_mutations": thread["pending_mutations"],
    }


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role") or "user"
        item: dict[str, Any] = {"role": role}
        if m.get("content") is not None:
            item["content"] = m["content"]
        if m.get("tool_calls"):
            item["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        if m.get("name"):
            item["name"] = m["name"]
        out.append(item)
    return out


def run_chat(
    session: Session,
    *,
    document_id: int,
    profile: LlmProfileConfig,
    messages: list[dict[str, Any]] | None = None,
    content: str | None = None,
    max_rounds: int = 40,
) -> dict[str, Any]:
    """Диалог с tool-calling. История и шаги сохраняются у статьи."""
    stored = get_thread(session, document_id)
    user_text = (content or "").strip()
    if user_text:
        prior = list(stored["messages"])
        seed = prior + [{"role": "user", "content": user_text}]
    else:
        seed = _normalize_messages(messages or [])
        for item in reversed(seed):
            if item.get("role") == "user" and item.get("content"):
                user_text = str(item["content"])
                break

    history = list(seed)
    if not history or history[0].get("role") != "system":
        history = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    pending: list[dict[str, Any]] = list(stored["pending_mutations"])
    new_events: list[dict[str, Any]] = []
    if (content or "").strip():
        new_events.append(_event("user", user_text))

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_trace: list[dict[str, Any]] = []

    assistant_text = ""
    for _ in range(max_rounds):
        result = chat_completion(
            profile,
            history,
            temperature=0.2,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )
        usage = result.get("usage") or {}
        for k in total_usage:
            total_usage[k] += int(usage.get(k) or 0)

        tool_calls = result.get("tool_calls") or []
        reply = result.get("content") or ""
        assistant_text = reply

        asst_msg: dict[str, Any] = {
            "role": "assistant",
            "content": reply or None,
        }
        if tool_calls:
            asst_msg["tool_calls"] = tool_calls
        history.append(asst_msg)
        if reply.strip():
            new_events.append(_event("assistant", reply.strip()))

        if not tool_calls:
            break

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments") or "{}"
            tc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            tool_result, mutation = execute_tool(
                session,
                document_id=document_id,
                name=name,
                arguments=raw_args,
            )
            if mutation:
                mutation = {**mutation, "id": f"mut_{uuid.uuid4().hex[:10]}"}
                pending.append(mutation)
                tool_result = {**tool_result, "proposal_id": mutation["id"]}

            summary = describe_tool(name, raw_args, tool_result)
            new_events.append(
                _event("tool", summary, tool=name, mutation_id=(mutation or {}).get("id"))
            )
            tool_trace.append(
                {
                    "tool_call_id": tc_id,
                    "name": name,
                    "arguments": raw_args,
                    "result": tool_result,
                    "summary": summary,
                }
            )
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    visible = [m for m in history if m.get("role") != "system"]
    events = list(stored["events"]) + new_events
    thread = save_thread(
        session,
        document_id,
        messages=visible,
        events=events,
        pending=pending,
    )

    return {
        "reply": assistant_text,
        "messages": visible,
        "pending_mutations": pending,
        "tool_trace": tool_trace,
        "events": thread["events"],
        "usage": total_usage,
        "document_id": document_id,
    }


def confirm_mutations(
    session: Session,
    *,
    document_id: int,
    project: ProjectState,
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Применить список подтверждённых мутаций (каждая в отдельном SAVEPOINT)."""
    applied: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for mut in mutations:
        action = mut.get("action") or mut.get("tool")
        args = mut.get("args") or {}
        mut_id = mut.get("id")
        try:
            with session.begin_nested():
                result = apply_mutation(
                    session,
                    document_id=document_id,
                    project=project,
                    action=str(action),
                    args=dict(args),
                )
            applied.append({"id": mut_id, "action": action, "result": result})
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": mut_id, "action": action, "error": str(exc)})

    applied_ids = {item["id"] for item in applied if item.get("id")}
    error_by_id = {item["id"]: item["error"] for item in errors if item.get("id")}
    stored = get_thread(session, document_id)
    remaining: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for item in stored["pending_mutations"]:
        item_id = item.get("id")
        if item_id in applied_ids:
            decisions.append(
                _event(
                    "decision",
                    f"Принято: {item.get('summary') or item.get('action') or 'действие'}",
                    status="accepted",
                    mutation_id=item_id,
                )
            )
            continue
        if item_id in error_by_id:
            decisions.append(
                _event(
                    "decision",
                    f"Не применено: {item.get('summary') or 'действие'}. {error_by_id[item_id]}",
                    status="error",
                    mutation_id=item_id,
                )
            )
        remaining.append(item)

    thread = save_thread(
        session,
        document_id,
        messages=stored["messages"],
        events=list(stored["events"]) + decisions,
        pending=remaining,
    )
    return {
        "ok": not errors,
        "applied": applied,
        "errors": errors,
        "document_id": document_id,
        **_public_thread(thread),
    }


def reject_mutations(
    session: Session,
    *,
    document_id: int,
    mutation_ids: list[str],
) -> dict[str, Any]:
    """Убрать предложения из очереди и записать отказ в журнал."""
    wanted = {mid for mid in mutation_ids if mid}
    stored = get_thread(session, document_id)
    remaining: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for item in stored["pending_mutations"]:
        item_id = item.get("id")
        if item_id in wanted:
            decisions.append(
                _event(
                    "decision",
                    f"Отклонено: {item.get('summary') or item.get('action') or 'действие'}",
                    status="rejected",
                    mutation_id=item_id,
                )
            )
            continue
        remaining.append(item)
    thread = save_thread(
        session,
        document_id,
        messages=stored["messages"],
        events=list(stored["events"]) + decisions,
        pending=remaining,
    )
    return _public_thread(thread)
