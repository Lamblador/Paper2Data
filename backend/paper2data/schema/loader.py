"""Загрузка YAML-шаблонов схем и разрешение imports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def templates_root() -> Path:
    """Корень репозитория / templates."""
    return Path(__file__).resolve().parents[3] / "templates"


def list_template_files(root: Path | None = None) -> list[Path]:
    base = root or templates_root()
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.glob("*.yaml")
        if p.is_file() and p.name != "project.yaml"
    )


def list_templates(root: Path | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in list_template_files(root):
        raw = _read_yaml(path)
        if not isinstance(raw, dict):
            continue
        if str(raw.get("kind") or "schema") != "schema":
            continue
        result.append(
            {
                "id": str(raw.get("id") or path.stem),
                "name": str(raw.get("name") or path.stem),
                "version": str(raw.get("version") or ""),
                "description": str(raw.get("description") or "").strip(),
                "imports": list(raw.get("imports") or []),
                "path": str(path),
            }
        )
    return result


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _index_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("id") or "")
        if key:
            out[key] = deepcopy(item)
    return out


def _merge_entity_types(
    base: list[dict[str, Any]], overlay: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = _index_by_id(base)
    for item in overlay:
        eid = str(item.get("id") or "")
        if not eid:
            continue
        if eid not in merged:
            merged[eid] = deepcopy(item)
            continue
        # Локальное определение перекрывает импортированное целиком.
        merged[eid] = deepcopy(item)
    return list(merged.values())


def _merge_relation_types(
    base: list[dict[str, Any]], overlay: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = _index_by_id(base)
    for item in overlay:
        rid = str(item.get("id") or "")
        if not rid:
            continue
        merged[rid] = deepcopy(item)
    return list(merged.values())


def _apply_attribute_extensions(
    entity_types: list[dict[str, Any]], extensions: list[dict[str, Any]]
) -> None:
    # Без deepcopy — мутируем те же объекты, что в entity_types.
    by_id = {
        str(item.get("id") or ""): item
        for item in entity_types
        if item.get("id")
    }
    for ext in extensions:
        et_id = str(ext.get("entity_type") or "")
        attr_id = str(ext.get("attribute_id") or "")
        entity = by_id.get(et_id)
        if entity is None:
            continue
        attrs = entity.get("attributes") or []
        for attr in attrs:
            if str(attr.get("id") or "") != attr_id:
                continue
            add_vals = list(ext.get("add_enum_values") or [])
            existing = list(attr.get("enum_values") or [])
            for val in add_vals:
                if val not in existing:
                    existing.append(val)
            attr["enum_values"] = existing


def _uniq_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _normalize_extraction_group(raw: dict[str, Any]) -> dict[str, Any] | None:
    gid = str(raw.get("id") or "").strip()
    if not gid:
        return None
    group: dict[str, Any] = {
        "id": gid,
        "name": str(raw.get("name") or gid),
        "entities": _uniq_preserve([str(x) for x in (raw.get("entities") or [])]),
        "relations": _uniq_preserve([str(x) for x in (raw.get("relations") or [])]),
    }
    if raw.get("section_include") is not None:
        group["section_include"] = [str(x) for x in (raw.get("section_include") or [])]
    if raw.get("section_exclude") is not None:
        group["section_exclude"] = [str(x) for x in (raw.get("section_exclude") or [])]
    if raw.get("instructions") is not None:
        group["instructions"] = str(raw.get("instructions") or "").strip()
    return group


def _merge_extraction_groups(
    base: list[dict[str, Any]], overlay: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Склеивает группы по id: entities/relations дополняются, остальные поля — overlay."""
    order: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for src in (base, overlay):
        for raw in src:
            group = _normalize_extraction_group(raw) if isinstance(raw, dict) else None
            if group is None:
                continue
            gid = group["id"]
            if gid not in by_id:
                by_id[gid] = group
                order.append(gid)
                continue
            existing = by_id[gid]
            existing["entities"] = _uniq_preserve(
                list(existing.get("entities") or []) + list(group.get("entities") or [])
            )
            existing["relations"] = _uniq_preserve(
                list(existing.get("relations") or []) + list(group.get("relations") or [])
            )
            if group.get("name"):
                existing["name"] = group["name"]
            if "section_include" in group:
                existing["section_include"] = group["section_include"]
            if "section_exclude" in group:
                existing["section_exclude"] = group["section_exclude"]
            if "instructions" in group:
                existing["instructions"] = group["instructions"]
    return [by_id[gid] for gid in order]


def load_raw_template(template_id: str, root: Path | None = None) -> dict[str, Any]:
    base = root or templates_root()
    path = base / f"{template_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Шаблон схемы не найден: {template_id}")
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"Неверный формат шаблона: {template_id}")
    data.setdefault("id", template_id)
    return data


def resolve_template(
    template_id: str,
    root: Path | None = None,
    *,
    _stack: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Загружает шаблон и рекурсивно разрешает imports + attribute_extensions."""
    if template_id in _stack:
        cycle = " → ".join([*_stack, template_id])
        raise ValueError(f"Циклический импорт схем: {cycle}")

    raw = load_raw_template(template_id, root)
    imports = [str(x) for x in (raw.get("imports") or [])]

    entity_types: list[dict[str, Any]] = []
    relation_types: list[dict[str, Any]] = []
    extraction_groups: list[dict[str, Any]] = []
    resolved_imports: list[str] = []

    for dep_id in imports:
        dep = resolve_template(dep_id, root, _stack=(*_stack, template_id))
        entity_types = _merge_entity_types(
            entity_types, list(dep.get("entity_types") or [])
        )
        relation_types = _merge_relation_types(
            relation_types, list(dep.get("relation_types") or [])
        )
        extraction_groups = _merge_extraction_groups(
            extraction_groups, list(dep.get("extraction_groups") or [])
        )
        resolved_imports.extend(list(dep.get("resolved_imports") or []))
        resolved_imports.append(dep_id)

    entity_types = _merge_entity_types(
        entity_types, list(raw.get("entity_types") or [])
    )
    relation_types = _merge_relation_types(
        relation_types, list(raw.get("relation_types") or [])
    )
    extraction_groups = _merge_extraction_groups(
        extraction_groups, list(raw.get("extraction_groups") or [])
    )

    extensions = list(raw.get("attribute_extensions") or [])
    if extensions:
        _apply_attribute_extensions(entity_types, extensions)

    # Дедуп импортов с сохранением порядка
    seen: set[str] = set()
    unique_imports: list[str] = []
    for item in resolved_imports:
        if item not in seen:
            seen.add(item)
            unique_imports.append(item)

    return {
        "version": str(raw.get("version") or "1.0"),
        "id": str(raw.get("id") or template_id),
        "name": str(raw.get("name") or template_id),
        "kind": str(raw.get("kind") or "schema"),
        "description": str(raw.get("description") or "").strip(),
        "imports": imports,
        "resolved_imports": unique_imports,
        "entity_types": entity_types,
        "relation_types": relation_types,
        "extraction_groups": extraction_groups,
        "attribute_extensions": extensions,
    }


def schema_to_yaml_dict(schema: dict[str, Any]) -> dict[str, Any]:
    """Нормализованный dict для сохранения в project schema.yaml."""
    out: dict[str, Any] = {
        "version": schema.get("version", "1.0"),
        "id": schema.get("id"),
        "name": schema.get("name"),
        "kind": "schema",
        "description": schema.get("description") or "",
        "imports": list(schema.get("imports") or []),
        "entity_types": deepcopy(list(schema.get("entity_types") or [])),
        "relation_types": deepcopy(list(schema.get("relation_types") or [])),
    }
    groups = list(schema.get("extraction_groups") or [])
    if groups:
        out["extraction_groups"] = deepcopy(groups)
    return out
