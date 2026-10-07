"""Сервис активной схемы проекта: применение шаблонов и CRUD типов."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState, save_project_settings
from paper2data.db.models import (
    AttributeDef,
    EntityType,
    RelationType,
    SchemaVersion,
)
from paper2data.schema.loader import (
    resolve_template,
    schema_to_yaml_dict,
)


SCHEMA_FILE = "schema.yaml"


def project_schema_path(project: ProjectState) -> Path:
    return project.root / SCHEMA_FILE


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return default


def serialize_attribute(attr: AttributeDef) -> dict[str, Any]:
    return {
        "id": attr.attr_id,
        "db_id": attr.id,
        "name": attr.name,
        "type": attr.attr_type,
        "required": attr.required,
        "unit": attr.unit,
        "enum_values": _loads(attr.enum_values_json, []),
        "llm_hint": attr.llm_hint,
        "default": attr.default_value,
        "order_index": attr.order_index,
    }


def serialize_entity_type(et: EntityType) -> dict[str, Any]:
    attrs = sorted(et.attributes, key=lambda a: a.order_index)
    return {
        "id": et.type_id,
        "db_id": et.id,
        "name": et.name,
        "description": et.description,
        "label_attribute": et.label_attribute,
        "order_index": et.order_index,
        "attributes": [serialize_attribute(a) for a in attrs],
    }


def serialize_relation_type(rt: RelationType) -> dict[str, Any]:
    return {
        "id": rt.type_id,
        "db_id": rt.id,
        "name": rt.name,
        "description": rt.description,
        "from": rt.from_type,
        "to": rt.to_type,
        "cardinality": rt.cardinality,
        "attributes": _loads(rt.attributes_json, []),
        "llm_hint": rt.llm_hint,
        "order_index": rt.order_index,
    }


def serialize_schema(sv: SchemaVersion) -> dict[str, Any]:
    entities = sorted(sv.entity_types, key=lambda e: e.order_index)
    relations = sorted(sv.relation_types, key=lambda r: r.order_index)
    return {
        "schema_version_id": sv.id,
        "version": sv.version,
        "template_id": sv.template_id,
        "name": sv.name,
        "is_active": sv.is_active,
        "created_at": sv.created_at.isoformat() if sv.created_at else None,
        "entity_types": [serialize_entity_type(e) for e in entities],
        "relation_types": [serialize_relation_type(r) for r in relations],
    }


def get_active_schema_version(session: Session) -> SchemaVersion | None:
    stmt = (
        select(SchemaVersion)
        .where(SchemaVersion.is_active.is_(True))
        .options(
            selectinload(SchemaVersion.entity_types).selectinload(EntityType.attributes),
            selectinload(SchemaVersion.relation_types),
        )
        .order_by(SchemaVersion.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _write_schema_yaml(project: ProjectState, schema_dict: dict[str, Any]) -> None:
    path = project_schema_path(project)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            schema_to_yaml_dict(schema_dict),
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def _insert_schema_rows(
    session: Session,
    *,
    version: int,
    template_id: str | None,
    name: str,
    entity_types: list[dict[str, Any]],
    relation_types: list[dict[str, Any]],
    yaml_snapshot: str,
) -> SchemaVersion:
    # Деактивируем предыдущие
    for old in session.scalars(select(SchemaVersion).where(SchemaVersion.is_active)).all():
        old.is_active = False

    sv = SchemaVersion(
        version=version,
        template_id=template_id,
        name=name,
        yaml_snapshot=yaml_snapshot,
        is_active=True,
    )
    session.add(sv)
    session.flush()

    for i, et in enumerate(entity_types):
        entity = EntityType(
            schema_version_id=sv.id,
            type_id=str(et["id"]),
            name=str(et.get("name") or et["id"]),
            description=str(et.get("description") or ""),
            label_attribute=et.get("label_attribute"),
            order_index=i,
        )
        session.add(entity)
        session.flush()
        for j, attr in enumerate(list(et.get("attributes") or [])):
            session.add(
                AttributeDef(
                    entity_type_id=entity.id,
                    attr_id=str(attr["id"]),
                    name=str(attr.get("name") or attr["id"]),
                    attr_type=str(attr.get("type") or "text"),
                    required=bool(attr.get("required", False)),
                    unit=attr.get("unit"),
                    enum_values_json=_dumps(list(attr.get("enum_values") or [])),
                    llm_hint=str(attr.get("llm_hint") or ""),
                    default_value=(
                        None
                        if attr.get("default") is None
                        else str(attr.get("default"))
                    ),
                    order_index=j,
                )
            )

    for i, rt in enumerate(relation_types):
        session.add(
            RelationType(
                schema_version_id=sv.id,
                type_id=str(rt["id"]),
                name=str(rt.get("name") or rt["id"]),
                description=str(rt.get("description") or ""),
                from_type=str(rt.get("from") or ""),
                to_type=str(rt.get("to") or ""),
                cardinality=str(rt.get("cardinality") or "N:N"),
                attributes_json=_dumps(list(rt.get("attributes") or [])),
                llm_hint=str(rt.get("llm_hint") or ""),
                order_index=i,
            )
        )

    session.flush()
    return sv


def apply_template(
    session: Session,
    project: ProjectState,
    template_id: str,
) -> dict[str, Any]:
    resolved = resolve_template(template_id)
    prev = get_active_schema_version(session)
    next_version = 1 if prev is None else prev.version + 1

    snapshot = schema_to_yaml_dict(resolved)
    sv = _insert_schema_rows(
        session,
        version=next_version,
        template_id=resolved["id"],
        name=str(resolved.get("name") or template_id),
        entity_types=list(resolved.get("entity_types") or []),
        relation_types=list(resolved.get("relation_types") or []),
        yaml_snapshot=_dumps(snapshot),
    )

    project.settings.schema_template = template_id
    project.settings.active_schema = template_id
    save_project_settings(project)
    _write_schema_yaml(project, snapshot)

    session.refresh(sv)
    # reload with relationships
    active = get_active_schema_version(session)
    assert active is not None
    return serialize_schema(active)


def schema_dict_from_db(sv: SchemaVersion) -> dict[str, Any]:
    data = serialize_schema(sv)
    snapshot = _loads(sv.yaml_snapshot or "", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    out: dict[str, Any] = {
        "version": str(data["version"]),
        "id": sv.template_id or "custom",
        "name": sv.name,
        "kind": "schema",
        "description": str(snapshot.get("description") or ""),
        "imports": list(snapshot.get("imports") or []),
        "entity_types": [
            {
                "id": e["id"],
                "name": e["name"],
                "description": e["description"],
                "label_attribute": e["label_attribute"],
                "attributes": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "type": a["type"],
                        "required": a["required"],
                        "unit": a["unit"],
                        "enum_values": a["enum_values"],
                        "llm_hint": a["llm_hint"],
                        "default": a["default"],
                    }
                    for a in e["attributes"]
                ],
            }
            for e in data["entity_types"]
        ],
        "relation_types": [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "from": r["from"],
                "to": r["to"],
                "cardinality": r["cardinality"],
                "attributes": r["attributes"],
                "llm_hint": r["llm_hint"],
            }
            for r in data["relation_types"]
        ],
    }
    groups = snapshot.get("extraction_groups")
    if isinstance(groups, list) and groups:
        out["extraction_groups"] = deepcopy(groups)
    return out


def bump_schema_from_active(
    session: Session,
    project: ProjectState,
    *,
    mutate,
) -> dict[str, Any]:
    """Копирует активную схему, применяет mutate(dict), сохраняет новую версию."""
    active = get_active_schema_version(session)
    if active is None:
        raise RuntimeError("Схема проекта не применена")

    schema = schema_dict_from_db(active)
    mutate(schema)

    next_version = active.version + 1
    snapshot = schema_to_yaml_dict(schema)
    _insert_schema_rows(
        session,
        version=next_version,
        template_id=active.template_id,
        name=str(schema.get("name") or active.name),
        entity_types=list(schema.get("entity_types") or []),
        relation_types=list(schema.get("relation_types") or []),
        yaml_snapshot=_dumps(snapshot),
    )
    _write_schema_yaml(project, snapshot)
    session.flush()
    fresh = get_active_schema_version(session)
    assert fresh is not None
    return serialize_schema(fresh)


def upsert_entity_type(
    session: Session,
    project: ProjectState,
    payload: dict[str, Any],
) -> dict[str, Any]:
    type_id = str(payload["id"]).strip()
    if not type_id:
        raise ValueError("id типа сущности обязателен")

    def mutate(schema: dict[str, Any]) -> None:
        entities = list(schema.get("entity_types") or [])
        found = None
        for et in entities:
            if et["id"] == type_id:
                found = et
                break
        if found is None:
            found = {
                "id": type_id,
                "name": payload.get("name") or type_id,
                "description": payload.get("description") or "",
                "label_attribute": payload.get("label_attribute"),
                "attributes": list(payload.get("attributes") or []),
            }
            entities.append(found)
        else:
            if "name" in payload:
                found["name"] = payload["name"]
            if "description" in payload:
                found["description"] = payload["description"]
            if "label_attribute" in payload:
                found["label_attribute"] = payload["label_attribute"]
            if "attributes" in payload and payload["attributes"] is not None:
                found["attributes"] = list(payload["attributes"])
        schema["entity_types"] = entities
        if payload.get("name"):
            # keep schema name
            pass

    return bump_schema_from_active(session, project, mutate=mutate)


def delete_entity_type(
    session: Session, project: ProjectState, type_id: str
) -> dict[str, Any]:
    def mutate(schema: dict[str, Any]) -> None:
        schema["entity_types"] = [
            e for e in (schema.get("entity_types") or []) if e.get("id") != type_id
        ]
        # Удаляем связи, ссылающиеся на тип
        schema["relation_types"] = [
            r
            for r in (schema.get("relation_types") or [])
            if r.get("from") != type_id and r.get("to") != type_id
        ]

    return bump_schema_from_active(session, project, mutate=mutate)


def upsert_attribute(
    session: Session,
    project: ProjectState,
    entity_type_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    attr_id = str(payload["id"]).strip()
    if not attr_id:
        raise ValueError("id атрибута обязателен")

    def mutate(schema: dict[str, Any]) -> None:
        entities = list(schema.get("entity_types") or [])
        target = next((e for e in entities if e.get("id") == entity_type_id), None)
        if target is None:
            raise ValueError(f"Тип сущности не найден: {entity_type_id}")
        attrs = list(target.get("attributes") or [])
        found = next((a for a in attrs if a.get("id") == attr_id), None)
        body = {
            "id": attr_id,
            "name": payload.get("name") or attr_id,
            "type": payload.get("type") or "text",
            "required": bool(payload.get("required", False)),
            "unit": payload.get("unit"),
            "enum_values": list(payload.get("enum_values") or []),
            "llm_hint": payload.get("llm_hint") or "",
            "default": payload.get("default"),
        }
        if found is None:
            attrs.append(body)
        else:
            found.update(body)
        target["attributes"] = attrs
        schema["entity_types"] = entities

    return bump_schema_from_active(session, project, mutate=mutate)


def delete_attribute(
    session: Session,
    project: ProjectState,
    entity_type_id: str,
    attr_id: str,
) -> dict[str, Any]:
    def mutate(schema: dict[str, Any]) -> None:
        for et in schema.get("entity_types") or []:
            if et.get("id") != entity_type_id:
                continue
            et["attributes"] = [
                a for a in (et.get("attributes") or []) if a.get("id") != attr_id
            ]

    return bump_schema_from_active(session, project, mutate=mutate)


def upsert_relation_type(
    session: Session,
    project: ProjectState,
    payload: dict[str, Any],
) -> dict[str, Any]:
    type_id = str(payload["id"]).strip()
    if not type_id:
        raise ValueError("id типа связи обязателен")

    def mutate(schema: dict[str, Any]) -> None:
        relations = list(schema.get("relation_types") or [])
        found = next((r for r in relations if r.get("id") == type_id), None)
        body = {
            "id": type_id,
            "name": payload.get("name") or type_id,
            "description": payload.get("description") or "",
            "from": payload.get("from") or (found or {}).get("from") or "",
            "to": payload.get("to") or (found or {}).get("to") or "",
            "cardinality": payload.get("cardinality")
            or (found or {}).get("cardinality")
            or "N:N",
            "attributes": list(
                payload.get("attributes")
                if payload.get("attributes") is not None
                else (found or {}).get("attributes")
                or []
            ),
            "llm_hint": payload.get("llm_hint")
            if "llm_hint" in payload
            else (found or {}).get("llm_hint") or "",
        }
        if not body["from"] or not body["to"]:
            raise ValueError("Для связи нужны from и to")
        if found is None:
            relations.append(body)
        else:
            found.update(body)
        schema["relation_types"] = relations

    return bump_schema_from_active(session, project, mutate=mutate)


def delete_relation_type(
    session: Session, project: ProjectState, type_id: str
) -> dict[str, Any]:
    def mutate(schema: dict[str, Any]) -> None:
        schema["relation_types"] = [
            r for r in (schema.get("relation_types") or []) if r.get("id") != type_id
        ]

    return bump_schema_from_active(session, project, mutate=mutate)


def clone_for_edit(data: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(data)
