"""Jinja2-промпты, JSON Schema structured output, few-shot из GoldSnapshot."""

from __future__ import annotations

import json
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError

from paper2data.extraction.recipes import default_strategy_for_intelligence


def _attr_json_schema(attr: dict[str, Any]) -> dict[str, Any]:
    t = str(attr.get("type") or "text")
    schema: dict[str, Any] = {"title": attr.get("name") or attr.get("id")}
    if attr.get("llm_hint"):
        schema["description"] = attr["llm_hint"]
    if t in {"number", "number_with_unit"}:
        schema["type"] = ["number", "string", "null"]
    elif t == "bool":
        schema["type"] = ["boolean", "null"]
    elif t == "enum":
        vals = list(attr.get("enum_values") or [])
        schema["type"] = ["string", "null"]
        if vals:
            schema["enum"] = vals + [None]
    else:
        schema["type"] = ["string", "null"]
    return schema


def entity_types_to_json_schema(
    entity_types: list[dict[str, Any]],
    *,
    relation_types: list[dict[str, Any]] | None = None,
    mode: str = "entities",
) -> dict[str, Any]:
    """JSON Schema для structured output LLM.

    mode: entities | relations | subgraph | abbreviations
    """
    if mode == "abbreviations":
        return {
            "type": "object",
            "properties": {
                "abbreviations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "expansion": {"type": "string"},
                            "quote": {"type": "string"},
                            "block_hint": {"type": ["string", "null"]},
                        },
                        "required": ["code", "expansion", "quote"],
                    },
                }
            },
            "required": ["abbreviations"],
        }

    entity_item = {
        "type": "object",
        "properties": {
            "temp_id": {
                "type": "string",
                "description": "Локальный id внутри ответа (e1, e2, …)",
            },
            "type": {
                "type": "string",
                "enum": [e["id"] for e in entity_types] or ["Unknown"],
            },
            "label": {"type": ["string", "null"]},
            "attributes": {"type": "object", "additionalProperties": True},
            "quote": {
                "type": "string",
                "description": "Дословная цитата из текста статьи",
            },
            "block_hint": {
                "type": ["string", "null"],
                "description": "Подсказка блока: id или начало текста",
            },
        },
        "required": ["type", "attributes", "quote", "block_hint"],
    }

    rel_enum = [r["id"] for r in (relation_types or [])] or ["RELATED"]
    relation_item = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": rel_enum},
            "source_temp_id": {"type": "string"},
            "target_temp_id": {"type": "string"},
            "source_label": {"type": ["string", "null"]},
            "target_label": {"type": ["string", "null"]},
            "attributes": {"type": "object", "additionalProperties": True},
            "quote": {"type": "string"},
            "block_hint": {"type": ["string", "null"]},
        },
        "required": ["type", "quote", "block_hint"],
    }

    if mode == "entities":
        return {
            "type": "object",
            "properties": {"entities": {"type": "array", "items": entity_item}},
            "required": ["entities"],
        }
    if mode == "relations":
        return {
            "type": "object",
            "properties": {"relations": {"type": "array", "items": relation_item}},
            "required": ["relations"],
        }
    # subgraph / iterative / one_shot
    return {
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": entity_item},
            "relations": {"type": "array", "items": relation_item},
            "done": {
                "type": "boolean",
                "description": "true, если больше сущностей целевого типа нет (iterative)",
            },
        },
        "required": ["entities", "relations"],
    }


def schema_description_text(schema: dict[str, Any], entity_filter: list[str] | None = None) -> str:
    lines: list[str] = [f"Схема: {schema.get('name') or schema.get('id')}"]
    entities = schema.get("entity_types") or []
    relations = schema.get("relation_types") or []
    if entity_filter:
        allow = set(entity_filter)
        entities = [e for e in entities if e.get("id") in allow]
        relations = [
            r
            for r in relations
            if r.get("from") in allow or r.get("to") in allow
        ]
    for et in entities:
        lines.append(f"- Сущность {et['id']} ({et.get('name')}): {et.get('description') or ''}")
        for attr in et.get("attributes") or []:
            req = "обязательный" if attr.get("required") else "опциональный"
            hint = attr.get("llm_hint") or ""
            lines.append(
                f"    · {attr['id']}: {attr.get('type')} ({req})"
                + (f" — {hint}" if hint else "")
            )
    for rt in relations:
        lines.append(
            f"- Связь {rt['id']}: {rt.get('from')} → {rt.get('to')} "
            f"({rt.get('cardinality')}) {rt.get('description') or ''}"
        )
        if rt.get("llm_hint"):
            lines.append(f"    подсказка: {rt['llm_hint']}")
    return "\n".join(lines)


def few_shot_from_gold(
    gold_payload: dict[str, Any],
    *,
    entity_types: list[str] | None = None,
    max_examples: int = 6,
) -> str:
    nodes = list(gold_payload.get("nodes") or [])
    edges = list(gold_payload.get("edges") or [])
    if entity_types:
        allow = set(entity_types)
        nodes = [n for n in nodes if n.get("entity_type") in allow]
    examples: list[str] = []
    for node in nodes[:max_examples]:
        quote = ""
        for ev in node.get("evidences") or []:
            if ev.get("quote"):
                quote = ev["quote"]
                break
        examples.append(
            json.dumps(
                {
                    "type": node.get("entity_type"),
                    "label": node.get("label"),
                    "attributes": node.get("attributes") or {},
                    "quote": quote,
                },
                ensure_ascii=False,
            )
        )
    if edges and len(examples) < max_examples:
        for edge in edges[: max(0, max_examples - len(examples))]:
            quote = ""
            for ev in edge.get("evidences") or []:
                if ev.get("quote"):
                    quote = ev["quote"]
                    break
            examples.append(
                json.dumps(
                    {
                        "relation": edge.get("relation_type"),
                        "source_node_id": edge.get("source_node_id"),
                        "target_node_id": edge.get("target_node_id"),
                        "quote": quote,
                    },
                    ensure_ascii=False,
                )
            )
    if not examples:
        return "(нет эталонных примеров)"
    return "\n".join(f"- {ex}" for ex in examples)


def existing_graph_summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    statuses: set[str] | None = None,
    max_nodes: int = 80,
) -> str:
    allow = statuses or {"manual", "accepted", "proposed"}
    nodes = [n for n in nodes if n.get("status") in allow]
    # Иначе промпт раздувается, и квантованная модель часто отвечает пустым done:true
    if len(nodes) > max_nodes:
        rank = {"accepted": 0, "manual": 1, "proposed": 2}
        nodes = sorted(nodes, key=lambda n: rank.get(str(n.get("status")), 9))[:max_nodes]
    node_ids = {n["id"] for n in nodes}
    edges = [
        e
        for e in edges
        if e.get("status") in allow
        and e.get("source_node_id") in node_ids
        and e.get("target_node_id") in node_ids
    ]
    lines = ["Узлы:"]
    for n in nodes:
        lines.append(
            f"- id={n['id']} type={n.get('entity_type')} label={n.get('label')!r} "
            f"attrs={json.dumps(n.get('attributes') or {}, ensure_ascii=False)}"
        )
    lines.append("Связи:")
    for e in edges:
        lines.append(
            f"- {e.get('relation_type')}: {e.get('source_node_id')} → {e.get('target_node_id')}"
        )
    if len(nodes) == 0:
        return "(граф пуст)"
    return "\n".join(lines)


def abbreviation_map_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "(словарь пуст)"
    return "\n".join(
        f"- {it.get('code')} → {it.get('expansion')}" for it in items
    )


def _jinja_env(templates: dict[str, str]) -> Environment:
    class DictLoader(BaseLoader):
        def get_source(self, environment: Environment, template: str):
            if template not in templates:
                raise TemplateError(f"Шаблон не найден: {template}")
            source = templates[template]
            return source, template, lambda: True

    env = Environment(
        loader=DictLoader(),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Позволяет {{ system }} внутри других шаблонов через include-подобный рендер
    return env


def render_prompt(
    recipe: dict[str, Any],
    template_name: str,
    context: dict[str, Any],
) -> str:
    templates = dict(recipe.get("prompt_templates") or {})
    if template_name not in templates:
        raise KeyError(f"В рецепте нет prompt_template: {template_name}")

    # Разворачиваем вложенный {{ system }} через предварительный рендер system
    env = Environment(undefined=StrictUndefined, autoescape=False)
    rendered_ctx = dict(context)
    if "system" in templates and "system" not in rendered_ctx:
        try:
            rendered_ctx["system"] = env.from_string(templates["system"]).render(**context)
        except TemplateError:
            rendered_ctx["system"] = templates["system"]

    try:
        return env.from_string(templates[template_name]).render(**rendered_ctx).strip()
    except TemplateError as exc:
        raise ValueError(f"Ошибка рендера промпта «{template_name}»: {exc}") from exc


def _join_instructions(base: str, extra: str) -> str:
    text = (base or "").strip()
    addon = (extra or "").strip()
    if text and addon:
        return f"{text}\n{addon}"
    return text or addon


def build_prompt_context(
    *,
    schema: dict[str, Any],
    recipe: dict[str, Any],
    step: dict[str, Any],
    section_text: str = "",
    tables_md: str = "",
    figure_captions: str = "",
    abbreviation_map: list[dict[str, Any]] | None = None,
    existing_nodes: list[dict[str, Any]] | None = None,
    existing_edges: list[dict[str, Any]] | None = None,
    gold_payload: dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    target_type: str | None = None,
    instructions: str = "",
    extra_instructions: str = "",
    prompt_template: str | None = None,
) -> dict[str, Any]:
    targets = step.get("targets") or {}
    entity_ids = list(targets.get("entities") or [])
    relation_ids = list(targets.get("relations") or [])
    all_entities = schema.get("entity_types") or []
    all_relations = schema.get("relation_types") or []
    filtered_entities = (
        [e for e in all_entities if e["id"] in entity_ids] if entity_ids else all_entities
    )
    filtered_relations = (
        [r for r in all_relations if r["id"] in relation_ids]
        if relation_ids
        else all_relations
    )
    mode = "subgraph"
    tmpl = prompt_template if prompt_template is not None else (step.get("prompt_template") or "")
    if tmpl == "resolve_codes":
        mode = "abbreviations"
    elif tmpl == "extract_entities":
        mode = "entities"
    elif tmpl == "extract_relations":
        mode = "relations"

    js = json_schema or entity_types_to_json_schema(
        filtered_entities, relation_types=filtered_relations, mode=mode
    )
    return {
        "schema": schema_description_text(schema, entity_filter=entity_ids or None),
        "entity_types": ", ".join(entity_ids) if entity_ids else "(все)",
        "relation_types": ", ".join(relation_ids) if relation_ids else "(все)",
        "json_schema": json.dumps(js, ensure_ascii=False, indent=2),
        "section_text": section_text or "(нет текста)",
        "tables_md": tables_md or "(нет таблиц)",
        "figure_captions": figure_captions or "(нет подписей)",
        "abbreviation_map": abbreviation_map_text(abbreviation_map or []),
        "existing_graph": existing_graph_summary(
            existing_nodes or [], existing_edges or []
        ),
        "few_shot": few_shot_from_gold(
            gold_payload or {},
            entity_types=entity_ids or None,
        ),
        "target_type": target_type
        or (targets.get("primary_entity") if targets else None)
        or (entity_ids[0] if entity_ids else ""),
        "instructions": _join_instructions(
            instructions
            or str(step.get("instructions") or "").strip()
            or step.get("description")
            or "",
            extra_instructions,
        ),
        "recipe_name": recipe.get("name") or "",
        "step_name": step.get("name") or "",
    }


def strategy_from_profile(intelligence_level: str, recipe_default: str | None = None) -> str:
    if recipe_default in {"iterative", "entities_first", "one_shot"}:
        # Явный default рецепта имеет приоритет только если профиль не high
        if (intelligence_level or "").lower() == "high" and recipe_default != "one_shot":
            return default_strategy_for_intelligence(intelligence_level)
        return recipe_default
    return default_strategy_for_intelligence(intelligence_level)
