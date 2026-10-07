"""Генерация рецепта из активной схемы + GoldSnapshot."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from paper2data.extraction.prompts import few_shot_from_gold
from paper2data.extraction.recipes import (
    default_strategy_for_intelligence,
    validate_recipe,
)


BASE_PROMPT_TEMPLATES = {
    "system": (
        "Ты — ассистент по извлечению структурированных данных из научной статьи.\n"
        "Извлекай только факты, явно присутствующие в тексте. Для каждого поля и\n"
        "каждой связи укажи quote (дословную цитату) и block_hint.\n"
        "Не выдумывай значения. Если данных нет — пропусти поле.\n"
        "Схема проекта:\n{{ schema }}\n{{ instructions }}\n"
    ),
    "extract_entities": (
        "{{ system }}\n"
        "Целевые типы сущностей: {{ entity_types }}.\n"
        "Словарь обозначений (если есть):\n{{ abbreviation_map }}\n"
        "Уже извлечённый граф (не дублируй те же label/code):\n{{ existing_graph }}\n"
        "Примеры (few-shot):\n{{ few_shot }}\n"
        "Текст ТЕКУЩЕГО фрагмента секции (не всей статьи целиком):\n{{ section_text }}\n"
        "Таблицы:\n{{ tables_md }}\n"
        "Подписи рисунков:\n{{ figure_captions }}\n"
        "Извлеки все целевые сущности из ЭТОГО фрагмента. Пустой список допустим,\n"
        "только если в фрагменте действительно нет таких фактов.\n"
        "Верни JSON по схеме:\n{{ json_schema }}\n"
    ),
    "extract_relations": (
        "{{ system }}\n"
        "Целевые типы связей: {{ relation_types }}.\n"
        "Известные сущности:\n{{ existing_graph }}\n"
        "Словарь обозначений:\n{{ abbreviation_map }}\n"
        "Текст ТЕКУЩЕГО фрагмента:\n{{ section_text }}\n"
        "Таблицы:\n{{ tables_md }}\n"
        "Свяжи сущности из графа фактами из этого фрагмента.\n"
        "Верни JSON по схеме:\n{{ json_schema }}\n"
    ),
    "iterative_next": (
        "{{ system }}\n"
        "Найди РОВНО ОДНУ следующую сущность типа {{ target_type }}, которой ещё нет\n"
        "в графе. Затем извлеки все её атрибуты и связанные узлы/рёбра, указанные в шаге.\n"
        "Уже в графе (не повторяй эти id/label):\n{{ existing_graph }}\n"
        "Словарь обозначений:\n{{ abbreviation_map }}\n"
        "Текст ТЕКУЩЕГО фрагмента (не всей статьи):\n{{ section_text }}\n"
        "Таблицы:\n{{ tables_md }}\n"
        "Если в ЭТОМ фрагменте новой сущности {{ target_type }} нет — верни\n"
        '{"entities":[],"relations":[],"done":true}. Иначе done:false и одна сущность.\n'
        "Верни JSON по схеме:\n{{ json_schema }}\n"
    ),
    "one_shot_section": (
        "{{ system }}\n"
        "Извлеки полный подграф для целевых типов за один проход по секции.\n"
        "Цели: сущности {{ entity_types }}, связи {{ relation_types }}.\n"
        "Словарь обозначений:\n{{ abbreviation_map }}\n"
        "Few-shot:\n{{ few_shot }}\n"
        "Текст:\n{{ section_text }}\n"
        "Таблицы:\n{{ tables_md }}\n"
        "Подписи:\n{{ figure_captions }}\n"
        "Верни JSON по схеме:\n{{ json_schema }}\n"
    ),
    "resolve_codes": (
        "{{ system }}\n"
        "Построй словарь обозначений: шифр/аббревиатура → полное имя или формула\n"
        "соединения/лиганда (например \"1\" → \"Eu(DBM)3BPhen\", \"DBM\" → \"dibenzoylmethane\").\n"
        "Текст (experimental + results + esi):\n{{ section_text }}\n"
        'Верни JSON: {"abbreviations": [{"code": "...", "expansion": "...", '
        '"quote": "...", "block_hint": "..."}]}.\n'
    ),
}

_DEFAULT_SECTIONS = ["abstract", "experimental", "results", "esi"]
_DEFAULT_EXCLUDE = ["introduction", "acknowledgments", "references"]


def _group_work_items(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Подграфы для шагов: extraction_groups + остаток вне групп."""
    entity_ids = [str(e["id"]) for e in (schema.get("entity_types") or []) if e.get("id")]
    relation_ids = [str(r["id"]) for r in (schema.get("relation_types") or []) if r.get("id")]
    groups = list(schema.get("extraction_groups") or [])
    if not groups:
        return [
            {
                "id": "all",
                "name": "Все сущности",
                "entities": entity_ids,
                "relations": relation_ids,
                "section_include": list(_DEFAULT_SECTIONS),
                "instructions": "",
            }
        ]

    covered_e: set[str] = set()
    covered_r: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw in groups:
        if not isinstance(raw, dict):
            continue
        gid = str(raw.get("id") or "").strip()
        if not gid:
            continue
        ents = [str(x) for x in (raw.get("entities") or []) if str(x) in entity_ids]
        rels = [str(x) for x in (raw.get("relations") or []) if str(x) in relation_ids]
        if not ents and not rels:
            continue
        covered_e.update(ents)
        covered_r.update(rels)
        item: dict[str, Any] = {
            "id": gid,
            "name": str(raw.get("name") or gid),
            "entities": ents,
            "relations": rels,
            "section_include": list(raw.get("section_include") or _DEFAULT_SECTIONS),
            "instructions": str(raw.get("instructions") or "").strip(),
        }
        if raw.get("section_exclude") is not None:
            item["section_exclude"] = list(raw.get("section_exclude") or [])
        items.append(item)

    leftover_e = [e for e in entity_ids if e not in covered_e]
    leftover_r = [r for r in relation_ids if r not in covered_r]
    if leftover_e or leftover_r:
        items.append(
            {
                "id": "ungrouped",
                "name": "Прочие типы",
                "entities": leftover_e,
                "relations": leftover_r,
                "section_include": list(_DEFAULT_SECTIONS),
                "instructions": "Извлеки оставшиеся типы схемы, не покрытые другими шагами.",
            }
        )
    return items


def _step_for_group(
    group: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    gid = str(group["id"])
    name = str(group.get("name") or gid)
    ents = list(group.get("entities") or [])
    rels = list(group.get("relations") or [])
    primary = "Compound" if "Compound" in ents else (ents[0] if ents else "Entity")
    section_include = list(group.get("section_include") or _DEFAULT_SECTIONS)
    instructions = str(group.get("instructions") or "").strip()
    step_id = f"extract_{gid}" if gid != "all" else "extract_entities_first"
    if strategy == "iterative" and gid == "all":
        step_id = "extract_iterative"
    elif strategy == "one_shot" and gid == "all":
        step_id = "extract_one_shot"

    step: dict[str, Any] = {
        "id": step_id,
        "name": name if gid != "all" else (
            f"{primary} (итеративно)" if strategy == "iterative"
            else ("One-shot по секциям" if strategy == "one_shot" else "Сущности, затем связи")
        ),
        "description": instructions or f"Извлечение группы «{name}».",
        "strategy": strategy,
        "section_include": section_include,
        "targets": {"entities": ents, "relations": rels},
        "human_review": True,
    }
    if instructions:
        step["instructions"] = instructions
    if group.get("section_exclude") is not None:
        step["section_exclude"] = list(group["section_exclude"])

    if strategy == "iterative":
        step["targets"]["primary_entity"] = primary
        step["prompt_template"] = "iterative_next"
        step["stop_when"] = "no_more_entities"
        step["name"] = f"{name} (итеративно)" if gid != "all" else step["name"]
    elif strategy == "one_shot":
        step["prompt_template"] = "one_shot_section"
        step["max_passes"] = 2
    else:
        step["phases"] = [
            {"name": "entities", "prompt_template": "extract_entities", "human_review": True},
            {"name": "relations", "prompt_template": "extract_relations", "human_review": True},
        ]
    return step


def generate_recipe_from_schema_and_gold(
    schema: dict[str, Any],
    *,
    gold_payload: dict[str, Any] | None = None,
    intelligence_level: str = "medium",
    recipe_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    schema_id = str(schema.get("id") or schema.get("template_id") or "custom")
    strategy = default_strategy_for_intelligence(intelligence_level)
    groups = _group_work_items(schema)

    few = few_shot_from_gold(gold_payload or {}, entity_types=None, max_examples=4)
    description = (
        f"Автогенерация из схемы «{schema.get('name') or schema_id}». "
        f"Стратегия по умолчанию: {strategy}."
    )
    if groups and groups[0].get("id") != "all":
        description += f" Шаги по {len(groups)} группам извлечения."
    if gold_payload:
        description += (
            f" Few-shot из эталона "
            f"({len(gold_payload.get('nodes') or [])} узлов)."
        )

    steps: list[dict[str, Any]] = [
        {
            "id": "resolve_abbreviations",
            "name": "Словарь обозначений",
            "description": "Первым шагом собрать шифры и аббревиатуры.",
            "strategy": "one_shot",
            "section_include": ["experimental", "results", "esi"],
            "section_exclude": list(_DEFAULT_EXCLUDE),
            "targets": {"entities": [], "relations": []},
            "prompt_template": "resolve_codes",
            "output_key": "abbreviation_map",
            "human_review": True,
        }
    ]

    for group in groups:
        steps.append(_step_for_group(group, strategy=strategy))

    pipeline = [s["id"] for s in steps]

    recipe = {
        "version": "1.0",
        "id": recipe_id or f"{schema_id}_extract",
        "name": name or f"Извлечение: {schema.get('name') or schema_id}",
        "kind": "recipe",
        "schema_id": schema_id,
        "description": description,
        "defaults": {
            "strategy": strategy,
            "section_include": list(_DEFAULT_SECTIONS),
            "section_exclude": list(_DEFAULT_EXCLUDE),
            "require_quote": True,
            "quote_verify_threshold": 90,
        },
        "prompt_templates": deepcopy(BASE_PROMPT_TEMPLATES),
        "steps": steps,
        "pipeline": pipeline,
        "meta": {
            "generated": True,
            "few_shot_preview": few[:500],
            "intelligence_level": intelligence_level,
            "extraction_groups": [g["id"] for g in groups],
        },
    }
    return validate_recipe(recipe)
