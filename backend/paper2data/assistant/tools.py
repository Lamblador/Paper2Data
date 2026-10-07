"""Инструменты ассистента над графом, извлечением и текстом статьи."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paper2data.db.models import Block
from paper2data.graph import service as graph_service

# OpenAI-совместимые описания функций
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_entities",
            "description": "Список узлов (сущностей) графа текущей статьи.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Фильтр по типу (например Compound, Component)",
                    },
                    "status": {
                        "type": "string",
                        "description": "Фильтр статуса: manual|proposed|accepted|rejected",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_block_text",
            "description": "Текст блока статьи по block_id.",
            "parameters": {
                "type": "object",
                "properties": {"block_id": {"type": "integer"}},
                "required": ["block_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_document",
            "description": "Поиск подстроки в блоках текста статьи (без учёта регистра).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": (
                "Предложить создание узла графа с обязательной цитатой из статьи. "
                "Сначала найди фрагмент через search_document/get_block_text. "
                "Не записывает в БД до подтверждения пользователя."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "label": {"type": "string"},
                    "attributes": {"type": "object"},
                    "quote": {
                        "type": "string",
                        "description": "Дословная цитата из текста статьи (обязательно)",
                    },
                    "block_id": {
                        "type": "integer",
                        "description": "id блока, откуда взята цитата",
                    },
                    "status": {"type": "string", "default": "proposed"},
                },
                "required": ["entity_type", "quote"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_attributes",
            "description": (
                "Предложить обновление атрибутов существующего узла. Ждёт подтверждения."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "integer"},
                    "attributes": {"type": "object"},
                    "merge": {
                        "type": "boolean",
                        "default": True,
                        "description": "true = слить с текущими атрибутами",
                    },
                    "label": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["node_id", "attributes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_evidence",
            "description": "Предложить добавить цитату (evidence) к узлу. Ждёт подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "integer"},
                    "quote": {"type": "string"},
                    "block_id": {"type": "integer"},
                    "page": {"type": "integer"},
                    "attribute_key": {"type": "string"},
                },
                "required": ["node_id", "quote"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_extraction_step",
            "description": (
                "Предложить запуск шага извлечения LLM. Ждёт подтверждения пользователя."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "step_id": {"type": "string"},
                    "phase": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["run_id"],
            },
        },
    },
]

MUTATING_TOOLS = frozenset(
    {"create_node", "update_attributes", "add_evidence", "run_extraction_step"}
)


def _tool_list_entities(
    session: Session, document_id: int, args: dict[str, Any]
) -> dict[str, Any]:
    nodes = graph_service.list_nodes(session, document_id)
    et = args.get("entity_type")
    st = args.get("status")
    if et:
        nodes = [n for n in nodes if n.get("entity_type") == et]
    if st:
        nodes = [n for n in nodes if n.get("status") == st]
    compact = [
        {
            "id": n["id"],
            "entity_type": n.get("entity_type"),
            "label": n.get("label"),
            "status": n.get("status"),
            "attributes": n.get("attributes"),
        }
        for n in nodes[:80]
    ]
    return {"count": len(nodes), "entities": compact, "truncated": len(nodes) > 80}


def _tool_get_block_text(
    session: Session, document_id: int, args: dict[str, Any]
) -> dict[str, Any]:
    block_id = int(args["block_id"])
    block = session.get(Block, block_id)
    if block is None or block.document_id != document_id:
        return {"ok": False, "error": f"Блок не найден: {block_id}"}
    return {
        "ok": True,
        "block_id": block.id,
        "kind": block.kind,
        "page": block.page,
        "text": block.text,
    }


def _tool_search_document(
    session: Session, document_id: int, args: dict[str, Any]
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or 10)
    if not query:
        return {"ok": False, "error": "Пустой query", "hits": []}
    q_lower = query.lower()
    rows = session.scalars(
        select(Block)
        .where(Block.document_id == document_id)
        .order_by(Block.page, Block.order_index)
    ).all()
    hits: list[dict[str, Any]] = []
    for b in rows:
        text = b.text or ""
        idx = text.lower().find(q_lower)
        if idx < 0:
            continue
        start = max(0, idx - 40)
        end = min(len(text), idx + len(query) + 80)
        hits.append(
            {
                "block_id": b.id,
                "page": b.page,
                "kind": b.kind,
                "snippet": text[start:end],
            }
        )
        if len(hits) >= limit:
            break
    return {"ok": True, "query": query, "hits": hits, "count": len(hits)}


def _proposal(
    tool_name: str, args: dict[str, Any], summary: str
) -> dict[str, Any]:
    return {
        "needs_confirm": True,
        "mutating": True,
        "tool": tool_name,
        "action": tool_name,
        "args": args,
        "summary": summary,
        "status": "pending",
    }


def execute_tool(
    session: Session,
    *,
    document_id: int,
    name: str,
    arguments: dict[str, Any] | str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Выполнить инструмент.

    Возвращает (результат_для_LLM, pending_mutation|None).
    Мутирующие инструменты не пишут в БД — только формируют предложение.
    """
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            args = {}
    else:
        args = dict(arguments or {})

    if name == "list_entities":
        return _tool_list_entities(session, document_id, args), None
    if name == "get_block_text":
        return _tool_get_block_text(session, document_id, args), None
    if name == "search_document":
        return _tool_search_document(session, document_id, args), None

    if name == "create_node":
        et = args.get("entity_type") or "?"
        label = args.get("label") or ""
        quote = str(args.get("quote") or "").strip()
        if not quote:
            return {
                "ok": False,
                "error": "Нужна дословная цитата quote из текста статьи. Сначала search_document.",
            }, None
        prop = _proposal(
            name,
            {
                "entity_type": et,
                "label": args.get("label"),
                "attributes": args.get("attributes") or {},
                "quote": quote,
                "block_id": args.get("block_id"),
                "page": args.get("page"),
                "status": "proposed",
            },
            f"Создать узел «{et}»{f' ({label})' if label else ''} ← «{quote[:80]}»",
        )
        return {
            "ok": True,
            "proposed": True,
            "message": "Предложение создано. Пользователь должен подтвердить.",
            "proposal": prop,
        }, prop

    if name == "update_attributes":
        node_id = args.get("node_id")
        prop = _proposal(
            name,
            {
                "node_id": node_id,
                "attributes": args.get("attributes") or {},
                "merge": args.get("merge", True),
                "label": args.get("label"),
                "status": args.get("status"),
            },
            f"Обновить атрибуты узла #{node_id}",
        )
        return {
            "ok": True,
            "proposed": True,
            "message": "Предложение обновления ждёт подтверждения.",
            "proposal": prop,
        }, prop

    if name == "add_evidence":
        node_id = args.get("node_id")
        quote = str(args.get("quote") or "")[:80]
        prop = _proposal(
            name,
            {
                "node_id": node_id,
                "quote": args.get("quote") or "",
                "block_id": args.get("block_id"),
                "page": args.get("page"),
                "attribute_key": args.get("attribute_key"),
                "created_by": "assistant",
                "target_kind": "attribute" if args.get("attribute_key") else "node",
            },
            f"Добавить цитату к узлу #{node_id}: «{quote}»",
        )
        return {
            "ok": True,
            "proposed": True,
            "message": "Предложение evidence ждёт подтверждения.",
            "proposal": prop,
        }, prop

    if name == "run_extraction_step":
        run_id = args.get("run_id")
        prop = _proposal(
            name,
            {
                "run_id": run_id,
                "step_id": args.get("step_id"),
                "phase": args.get("phase"),
                "dry_run": bool(args.get("dry_run", False)),
            },
            f"Запустить шаг извлечения run_id={run_id}",
        )
        return {
            "ok": True,
            "proposed": True,
            "message": "Запуск шага извлечения ждёт подтверждения.",
            "proposal": prop,
        }, prop

    return {"ok": False, "error": f"Неизвестный инструмент: {name}"}, None


def apply_mutation(
    session: Session,
    *,
    document_id: int,
    project: Any,
    action: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Применить подтверждённое мутирующее действие."""
    if action == "create_node":
        quote = str(args.get("quote") or "").strip()
        if not quote:
            raise ValueError(
                "Нужна дословная цитата (quote) из текста статьи — без опоры на текст узел не создаётся."
            )
        from paper2data.extraction.quotes import score_quote_in_block, verify_quote_against_blocks

        blocks = [
            {
                "id": b.id,
                "text": b.text or "",
                "page": b.page,
                "bbox": None,
            }
            for b in session.scalars(
                select(Block).where(Block.document_id == document_id).order_by(Block.id)
            ).all()
        ]
        block_id = args.get("block_id")
        chosen = None
        if block_id is not None:
            chosen = next((b for b in blocks if b["id"] == int(block_id)), None)
        if chosen is not None and score_quote_in_block(quote, str(chosen.get("text") or "")) < 75:
            chosen = None
        match = verify_quote_against_blocks(quote, blocks, threshold=85)
        if chosen is None and match.block_id is not None:
            chosen = next((b for b in blocks if b["id"] == match.block_id), None)
        payload = {
            "entity_type": args.get("entity_type"),
            "label": args.get("label"),
            "attributes": args.get("attributes") or {},
            "status": "proposed",
            "evidence": {
                "quote": quote,
                "block_id": (chosen or {}).get("id"),
                "page": (chosen or {}).get("page") or match.page or args.get("page"),
                "bbox": (chosen or {}).get("bbox"),
                "char_start": match.char_start,
                "char_end": match.char_end,
                "created_by": "assistant",
                "verified": bool(match.verified),
            },
        }
        node = graph_service.create_node(session, document_id, payload)
        return {"ok": True, "node": node}

    if action == "update_attributes":
        node_id = int(args["node_id"])
        current = graph_service.get_node(session, node_id)
        if current["document_id"] != document_id:
            raise ValueError("Узел принадлежит другой статье")
        attrs = dict(current.get("attributes") or {})
        incoming = dict(args.get("attributes") or {})
        if args.get("merge", True):
            attrs.update(incoming)
        else:
            attrs = incoming
        payload: dict[str, Any] = {"attributes": attrs}
        if args.get("label") is not None:
            payload["label"] = args["label"]
        if args.get("status") is not None:
            payload["status"] = args["status"]
        node = graph_service.update_node(session, node_id, payload)
        return {"ok": True, "node": node}

    if action == "add_evidence":
        payload = {
            "target_kind": args.get("target_kind")
            or ("attribute" if args.get("attribute_key") else "node"),
            "node_id": int(args["node_id"]),
            "quote": args.get("quote") or "",
            "block_id": args.get("block_id"),
            "page": args.get("page"),
            "attribute_key": args.get("attribute_key"),
            "created_by": args.get("created_by") or "assistant",
            "verified": False,
        }
        ev = graph_service.create_evidence(session, payload)
        return {"ok": True, "evidence": ev}

    if action == "run_extraction_step":
        from paper2data.extraction import engine as extraction_engine

        result = extraction_engine.run_step(
            session,
            project,
            run_id=int(args["run_id"]),
            step_id=args.get("step_id"),
            phase=args.get("phase"),
            dry_run=bool(args.get("dry_run", False)),
        )
        return {"ok": True, "result": result}

    raise ValueError(f"Неизвестное действие: {action}")
