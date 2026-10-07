"""Движок извлечения: стратегии, прогон шага, предложение узлов/рёбер."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paper2data.core.project import ProjectState
from paper2data.db.models import Edge, ExtractionRun, Node, Recipe
from paper2data.extraction import chunks as chunk_mod
from paper2data.extraction.device_stack import (
    MAX_LOCAL_STACK_PASSES,
    audit_incomplete_device_stacks,
    focus_incomplete_device_instruction,
    focus_incomplete_devices_instruction,
    format_incomplete_stacks_summary,
    is_device_metrics_step,
    is_device_stack_step,
    is_luminescence_step,
    luminescence_policy_instructions,
    metrics_policy_instructions,
    stack_policy_instructions,
)
from paper2data.extraction.prompts import build_prompt_context, render_prompt
from paper2data.extraction.quotes import (
    DEFAULT_QUOTE_THRESHOLD,
    char_span,
    score_quote_in_block,
    verify_quote_against_blocks,
)
from paper2data.extraction.recipes import (
    default_strategy_for_intelligence,
    parse_recipe_yaml,
    recipe_to_yaml,
    resolve_recipe,
    validate_recipe,
)
from paper2data.graph import service as graph_service
from paper2data.llm import client as llm_client
from paper2data.llm import profiles as llm_profiles
from paper2data.llm.client import is_local_base_url
from paper2data.schema import service as schema_service


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def serialize_recipe_row(row: Recipe) -> dict[str, Any]:
    body = {}
    try:
        body = parse_recipe_yaml(row.yaml_body)
    except ValueError:
        body = {"id": row.recipe_id, "name": row.name}
    return {
        "db_id": row.id,
        "id": row.recipe_id,
        "name": row.name,
        "schema_id": row.schema_id,
        "version": row.version,
        "description": row.description,
        "is_active": row.is_active,
        "source_path": row.source_path,
        "steps": body.get("steps") or [],
        "pipeline": body.get("pipeline") or [],
        "defaults": body.get("defaults") or {},
        "prompt_templates": list((body.get("prompt_templates") or {}).keys()),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "body": body,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stats_dict(run: ExtractionRun) -> dict[str, Any]:
    stats = _loads(run.stats_json, {})
    return stats if isinstance(stats, dict) else {}


def _pipeline_ids(
    session: Session | None,
    project: ProjectState | None,
    recipe_id: str | None,
) -> list[str]:
    """Шаги рецепта. Сбой резолва не должен ронять список прогонов."""
    if session is None:
        return []
    try:
        body: dict[str, Any] | None = None
        if project is not None:
            body = get_active_recipe_body(session, project, recipe_id or None)
        elif recipe_id:
            row = session.scalars(
                select(Recipe)
                .where(Recipe.recipe_id == recipe_id, Recipe.is_active.is_(True))
                .order_by(Recipe.id.desc())
            ).first()
            if row is not None:
                body = parse_recipe_yaml(row.yaml_body)
        if not isinstance(body, dict):
            return []
        pipeline = [str(item) for item in (body.get("pipeline") or []) if item]
        if not pipeline:
            pipeline = [
                str(step["id"])
                for step in (body.get("steps") or [])
                if isinstance(step, dict) and step.get("id")
            ]
        return pipeline
    except Exception:
        return []


def _step_index(pipeline: list[str], current_step_id: str | None) -> int:
    if not current_step_id:
        return 0
    try:
        return pipeline.index(str(current_step_id)) + 1
    except ValueError:
        return 0


def _normalize_step_history(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    history: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("step_id"):
            continue
        status = str(item.get("status") or "")
        if status not in {"running", "done", "failed"}:
            status = "failed" if item.get("error") else "done"
        history.append(
            {
                "step_id": str(item["step_id"]),
                "status": status,
                "started_at": _opt_str(item.get("started_at")),
                "finished_at": _opt_str(item.get("finished_at")),
                "nodes": _as_int(item.get("nodes")),
                "edges": _as_int(item.get("edges")),
                "abbreviations": _as_int(item.get("abbreviations")),
                "prompt_tokens": _as_int(item.get("prompt_tokens")),
                "completion_tokens": _as_int(item.get("completion_tokens")),
                "error": _opt_str(item.get("error")),
            }
        )
    return history


def _order_step_history(
    history: list[dict[str, Any]],
    pipeline: list[str],
) -> list[dict[str, Any]]:
    if not pipeline:
        return history
    order = {str(step_id): index for index, step_id in enumerate(pipeline)}
    return sorted(history, key=lambda item: order.get(str(item["step_id"]), len(order)))


def _upsert_step_history(
    stats: dict[str, Any],
    pipeline: list[str],
    entry: dict[str, Any],
) -> None:
    """Повтор того же step_id заменяет запись; порядок — как в pipeline."""
    step_id = str(entry.get("step_id") or "")
    history = [
        item
        for item in _normalize_step_history(stats.get("steps_history"))
        if item["step_id"] != step_id
    ]
    history.extend(_normalize_step_history([entry]))
    stats["steps_history"] = _order_step_history(history, pipeline)


def _run_counts(session: Session | None, run_id: int | None) -> dict[str, int]:
    counts = {"proposed": 0, "accepted": 0, "rejected": 0, "nodes": 0, "edges": 0}
    if session is None or run_id is None:
        return counts
    for model, total_key in ((Node, "nodes"), (Edge, "edges")):
        rows = session.execute(
            select(model.status, func.count())
            .where(model.run_id == run_id)
            .group_by(model.status)
        ).all()
        for status, amount in rows:
            amount_i = _as_int(amount)
            counts[total_key] += amount_i
            if status in {"proposed", "accepted", "rejected"}:
                counts[status] += amount_i
    return counts


def serialize_run(
    run: ExtractionRun,
    session: Session | None = None,
    project: ProjectState | None = None,
) -> dict[str, Any]:
    stats = _stats_dict(run)
    pipeline = _pipeline_ids(session, project, run.recipe_id)
    steps_history = _order_step_history(
        _normalize_step_history(stats.get("steps_history")),
        pipeline,
    )
    return {
        "id": run.id,
        "document_id": run.document_id,
        "recipe_db_id": run.recipe_db_id,
        "recipe_id": run.recipe_id,
        "llm_profile_id": run.llm_profile_id,
        "strategy": run.strategy,
        "status": run.status,
        "current_step_id": run.current_step_id,
        "abbreviation_map": _loads(run.abbreviation_map_json, []),
        "stats": stats,
        "options": _run_options(run),
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "pipeline": pipeline,
        "steps_total": len(pipeline),
        "step_index": _step_index(pipeline, run.current_step_id),
        "steps_history": steps_history,
        "counts": _run_counts(session, run.id),
    }


def upsert_recipe_db(
    session: Session,
    project: ProjectState,
    recipe: dict[str, Any],
    *,
    source_path: str | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    validated = validate_recipe(recipe)
    yaml_body = recipe_to_yaml(validated)
    if activate:
        for old in session.scalars(
            select(Recipe).where(
                Recipe.recipe_id == validated["id"], Recipe.is_active.is_(True)
            )
        ).all():
            old.is_active = False

    row = Recipe(
        recipe_id=validated["id"],
        name=validated["name"],
        schema_id=validated.get("schema_id"),
        version=str(validated.get("version") or "1.0"),
        yaml_body=yaml_body,
        description=str(validated.get("description") or ""),
        is_active=activate,
        source_path=source_path,
    )
    session.add(row)
    session.flush()

    # Также на диск проекта
    from paper2data.extraction.recipes import save_recipe_to_project

    path = save_recipe_to_project(project.root, validated)
    row.source_path = str(path)
    session.flush()
    return serialize_recipe_row(row)


def list_recipes_db(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(Recipe).order_by(Recipe.id.desc())).all()
    return [serialize_recipe_row(r) for r in rows]


def get_recipe_db(session: Session, recipe_db_id: int) -> dict[str, Any]:
    row = session.get(Recipe, recipe_db_id)
    if row is None:
        raise LookupError(f"Рецепт не найден: {recipe_db_id}")
    return serialize_recipe_row(row)


def get_active_recipe_body(
    session: Session,
    project: ProjectState,
    recipe_id: str | None = None,
) -> dict[str, Any]:
    if recipe_id:
        row = session.scalars(
            select(Recipe)
            .where(Recipe.recipe_id == recipe_id, Recipe.is_active.is_(True))
            .order_by(Recipe.id.desc())
        ).first()
        if row:
            return parse_recipe_yaml(row.yaml_body)
        return resolve_recipe(recipe_id, project_root=project.root)
    row = session.scalars(
        select(Recipe).where(Recipe.is_active.is_(True)).order_by(Recipe.id.desc())
    ).first()
    if row:
        return parse_recipe_yaml(row.yaml_body)
    # bundled example
    return resolve_recipe("example_coordination_extract", project_root=project.root)


def _lookup_hint_block(
    blocks: list[dict[str, Any]],
    block_hint: str | None,
) -> dict[str, Any] | None:
    if not block_hint:
        return None
    hint = str(block_hint).strip()
    if hint.isdigit():
        bid = int(hint)
        for block in blocks:
            if block.get("id") == bid:
                return block
    if hint.startswith("block:"):
        try:
            bid = int(hint.split(":", 1)[1].split()[0])
        except ValueError:
            bid = None
        if bid is not None:
            for block in blocks:
                if block.get("id") == bid:
                    return block
    hint_l = hint.lower()
    if not hint_l:
        return None
    for block in blocks:
        if hint_l in (block.get("text") or "").lower():
            return block
    return None


def _find_block_for_hint(
    blocks: list[dict[str, Any]],
    block_hint: str | None,
    quote: str,
) -> dict[str, Any] | None:
    hinted = _lookup_hint_block(blocks, block_hint)
    if hinted is not None and quote and score_quote_in_block(quote, str(hinted.get("text") or "")) < 75:
        hinted = None
    if hinted is not None:
        return hinted
    match = verify_quote_against_blocks(quote, blocks, threshold=50)
    if match.block_id is None:
        return None
    for block in blocks:
        if block.get("id") == match.block_id:
            return block
    return None


def _quote_evidence(
    quote: str,
    blocks: list[dict[str, Any]],
    block_hint: Any,
    threshold: float,
) -> dict[str, Any]:
    """Опора на блок, в котором реально лежит цитата, а не номер страницы."""
    block = _find_block_for_hint(blocks, str(block_hint) if block_hint else None, quote)
    match = verify_quote_against_blocks(quote, blocks, threshold=threshold)
    if block is None and match.block_id is not None:
        block = next((item for item in blocks if item.get("id") == match.block_id), None)
    same = block is not None and block.get("id") == match.block_id
    if same:
        char_start, char_end = match.char_start, match.char_end
        verified = bool(match.verified)
    elif block is not None:
        text = str(block.get("text") or "")
        char_start, char_end = char_span(quote, text)
        verified = score_quote_in_block(quote, text) >= threshold
    else:
        char_start, char_end = None, None
        verified = False
    return {
        "quote": quote,
        "block_id": None if block is None else block.get("id"),
        "page": None if block is None else block.get("page"),
        "bbox": None if block is None else block.get("bbox"),
        "char_start": char_start,
        "char_end": char_end,
        "created_by": "llm",
        "verified": verified,
    }


def _propose_entity(
    session: Session,
    document_id: int,
    run_id: int,
    entity: dict[str, Any],
    blocks: list[dict[str, Any]],
    *,
    threshold: float,
    temp_id_map: dict[str, int],
    offset: int,
) -> dict[str, Any] | None:
    type_id = entity.get("type")
    if not type_id:
        return None
    quote = str(entity.get("quote") or "").strip()
    if not quote:
        # Без цитаты сущность не опирается на текст — не принимаем в очередь
        return None
    attributes = dict(entity.get("attributes") or {})
    evidence = _quote_evidence(quote, blocks, entity.get("block_hint"), threshold)
    try:
        node = graph_service.create_node(
            session,
            document_id,
            {
                "entity_type": type_id,
                "label": entity.get("label"),
                "attributes": attributes,
                "status": "proposed",
                "run_id": run_id,
                "pos_x": 60 + (offset % 6) * 160,
                "pos_y": 40 + (offset // 6) * 110,
                "evidence": evidence,
            },
        )
    except (LookupError, ValueError, RuntimeError):
        return None
    temp = entity.get("temp_id") or entity.get("label") or str(node["id"])
    temp_id_map[str(temp)] = node["id"]
    # Модель часто пишет target_temp_id: "3" вместо "e3"
    temp_s = str(temp)
    if temp_s.startswith("e") and temp_s[1:].isdigit():
        temp_id_map[temp_s[1:]] = node["id"]
    return node


def _propose_relation(
    session: Session,
    document_id: int,
    run_id: int,
    relation: dict[str, Any],
    blocks: list[dict[str, Any]],
    *,
    threshold: float,
    temp_id_map: dict[str, int],
    label_index: dict[str, int],
) -> dict[str, Any] | None:
    rel_type = relation.get("type")
    if not rel_type:
        return None
    source_id = None
    target_id = None
    if relation.get("source_temp_id") and str(relation["source_temp_id"]) in temp_id_map:
        source_id = temp_id_map[str(relation["source_temp_id"])]
    if relation.get("target_temp_id") and str(relation["target_temp_id"]) in temp_id_map:
        target_id = temp_id_map[str(relation["target_temp_id"])]
    if source_id is None and relation.get("source_label"):
        source_id = label_index.get(str(relation["source_label"]).strip().lower())
    if target_id is None and relation.get("target_label"):
        target_id = label_index.get(str(relation["target_label"]).strip().lower())
    # numeric ids from existing graph — только если это не ключ из temp_id_map текущего ответа
    src_raw = str(relation.get("source_temp_id") or "")
    tgt_raw = str(relation.get("target_temp_id") or "")
    if source_id is None and src_raw.isdigit() and src_raw not in temp_id_map:
        source_id = int(src_raw)
    if target_id is None and tgt_raw.isdigit() and tgt_raw not in temp_id_map:
        target_id = int(tgt_raw)
    if source_id is None or target_id is None:
        return None

    quote = str(relation.get("quote") or "")
    evidence = _quote_evidence(quote, blocks, relation.get("block_hint"), threshold)
    try:
        return graph_service.create_edge(
            session,
            document_id,
            {
                "relation_type": rel_type,
                "source_node_id": source_id,
                "target_node_id": target_id,
                "attributes": dict(relation.get("attributes") or {}),
                "status": "proposed",
                "run_id": run_id,
                "evidence": evidence,
            },
        )
    except (LookupError, ValueError, RuntimeError):
        return None


def _normalize_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Приводит ответ модели к {entities, relations, …}."""
    if not isinstance(data, dict):
        return {"entities": [], "relations": []}
    out = dict(data)
    entities = out.get("entities")
    if entities is None:
        for key in ("nodes", "compounds", "items", "objects"):
            if isinstance(out.get(key), list):
                entities = out[key]
                break
    if entities is None and isinstance(out.get("entity"), dict):
        entities = [out["entity"]]
    relations = out.get("relations")
    if relations is None:
        for key in ("edges", "links"):
            if isinstance(out.get(key), list):
                relations = out[key]
                break
    out["entities"] = entities if isinstance(entities, list) else []
    out["relations"] = relations if isinstance(relations, list) else []
    # type может приехать как entity_type
    for ent in out["entities"]:
        if isinstance(ent, dict) and not ent.get("type") and ent.get("entity_type"):
            ent["type"] = ent["entity_type"]
        if isinstance(ent, dict) and not ent.get("quote"):
            # иногда модель кладёт цитату в evidence/source
            ev = ent.get("evidence") or ent.get("source") or {}
            if isinstance(ev, dict) and ev.get("quote"):
                ent["quote"] = ev["quote"]
            elif isinstance(ev, str):
                ent["quote"] = ev
    return out


def _run_only_graph(
    graph: dict[str, Any],
    run_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Только узлы/рёбра текущего прогона (для слепого режима)."""
    nodes = [
        node
        for node in (graph.get("nodes") or [])
        if node.get("run_id") == run_id
        and node.get("status") in {"proposed", "accepted", "manual"}
    ]
    node_ids = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in (graph.get("edges") or [])
        if edge.get("run_id") == run_id
        and edge.get("status") in {"proposed", "accepted", "manual"}
        and edge.get("source_node_id") in node_ids
        and edge.get("target_node_id") in node_ids
    ]
    return nodes, edges


def _apply_llm_payload(
    session: Session,
    document_id: int,
    run_id: int,
    data: dict[str, Any],
    blocks: list[dict[str, Any]],
    *,
    threshold: float,
    blind: bool = False,
) -> dict[str, Any]:
    data = _normalize_llm_payload(data)
    graph = graph_service.get_graph(session, document_id)
    # Узлы текущего прогона (+ accepted/manual вне blind) — для дедупа и связей
    if blind:
        dedup_nodes, _ = _run_only_graph(graph, run_id)
    else:
        dedup_nodes = [
            n
            for n in graph["nodes"]
            if n.get("status") in {"accepted", "manual"}
            or (n.get("status") == "proposed" and n.get("run_id") == run_id)
        ]
    label_index = {
        str(n.get("label") or "").strip().lower(): n["id"]
        for n in dedup_nodes
        if n.get("label")
    }
    type_label_index: dict[tuple[str, str], int] = {}
    for n in dedup_nodes:
        label = str(n.get("label") or "").strip().lower()
        etype = str(n.get("entity_type") or "").strip()
        if label and etype:
            type_label_index[(etype, label)] = n["id"]
    temp_id_map: dict[str, int] = {
        str(n["id"]): n["id"] for n in (dedup_nodes if blind else graph["nodes"])
    }
    created_nodes: list[dict[str, Any]] = []
    created_edges: list[dict[str, Any]] = []
    skipped_entities = 0
    skipped_relations = 0
    deduped_entities = 0
    offset = len(graph["nodes"])

    def _map_temp(entity: dict[str, Any], node_id: int) -> None:
        temp = entity.get("temp_id") or entity.get("label") or str(node_id)
        temp_id_map[str(temp)] = node_id
        temp_s = str(temp)
        if temp_s.startswith("e") and temp_s[1:].isdigit():
            temp_id_map[temp_s[1:]] = node_id

    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            skipped_entities += 1
            continue
        type_id = str(entity.get("type") or entity.get("entity_type") or "").strip()
        label_key = str(entity.get("label") or "").strip().lower()
        if type_id and label_key and (type_id, label_key) in type_label_index:
            existing_id = type_label_index[(type_id, label_key)]
            _map_temp(entity, existing_id)
            deduped_entities += 1
            continue
        before = len(created_nodes)
        node = _propose_entity(
            session,
            document_id,
            run_id,
            entity,
            blocks,
            threshold=threshold,
            temp_id_map=temp_id_map,
            offset=offset + len(created_nodes),
        )
        if node:
            created_nodes.append(node)
            if node.get("label"):
                label_index[str(node["label"]).strip().lower()] = node["id"]
            etype = str(node.get("entity_type") or type_id or "").strip()
            nlabel = str(node.get("label") or "").strip().lower()
            if etype and nlabel:
                type_label_index[(etype, nlabel)] = node["id"]
        elif before == len(created_nodes):
            skipped_entities += 1

    for relation in data.get("relations") or []:
        if not isinstance(relation, dict):
            skipped_relations += 1
            continue
        edge = _propose_relation(
            session,
            document_id,
            run_id,
            relation,
            blocks,
            threshold=threshold,
            temp_id_map=temp_id_map,
            label_index=label_index,
        )
        if edge:
            created_edges.append(edge)
        else:
            skipped_relations += 1

    return {
        "nodes": created_nodes,
        "edges": created_edges,
        "done": bool(data.get("done")),
        "abbreviations": data.get("abbreviations"),
        "skipped_entities": skipped_entities,
        "skipped_relations": skipped_relations,
        "deduped_entities": deduped_entities,
    }


def create_run(
    session: Session,
    project: ProjectState,
    *,
    document_id: int,
    recipe_id: str | None = None,
    llm_profile_id: str | None = None,
    strategy: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_service.get_document(session, document_id)
    profiles = project.settings.llm_profiles
    if not profiles:
        raise RuntimeError("Нет LLM-профилей. Добавьте профиль в настройках.")
    profile = None
    if llm_profile_id:
        profile = next((p for p in profiles if p.id == llm_profile_id), None)
        if profile is None:
            raise LookupError(f"Профиль не найден: {llm_profile_id}")
    else:
        profile = profiles[0]

    recipe_body = get_active_recipe_body(session, project, recipe_id)
    recipe_row = session.scalars(
        select(Recipe)
        .where(Recipe.recipe_id == recipe_body["id"], Recipe.is_active.is_(True))
        .order_by(Recipe.id.desc())
    ).first()

    schema_row = schema_service.get_active_schema_version(session)
    active_schema_id = (
        str(schema_row.template_id or "") if schema_row is not None else ""
    )
    recipe_schema_id = str(recipe_body.get("schema_id") or "")
    stats: dict[str, Any] = {
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    if (
        recipe_schema_id
        and active_schema_id
        and recipe_schema_id != active_schema_id
    ):
        stats["warnings"] = [
            (
                f"Рецепт schema_id={recipe_schema_id!r} не совпадает с активной "
                f"схемой {active_schema_id!r}. Прогон использует активную схему."
            )
        ]

    resolved_strategy = strategy or default_strategy_for_intelligence(
        profile.intelligence_level
    )
    defaults = recipe_body.get("defaults") or {}
    if not strategy and defaults.get("strategy"):
        # профиль high → one_shot, иначе default рецепта
        if (profile.intelligence_level or "").lower() == "high":
            resolved_strategy = "one_shot"
        else:
            resolved_strategy = str(defaults["strategy"])

    normalized = normalize_run_options(options)
    abbr_json = "[]"
    copy_id = normalized.get("copy_abbreviations_from_run_id")
    if copy_id is not None:
        src = session.get(ExtractionRun, copy_id)
        if src is None:
            raise LookupError(f"Прогон для словаря сокращений не найден: {copy_id}")
        abbr_json = src.abbreviation_map_json or "[]"

    run = ExtractionRun(
        document_id=document_id,
        recipe_db_id=recipe_row.id if recipe_row else None,
        recipe_id=recipe_body["id"],
        llm_profile_id=profile.id,
        strategy=resolved_strategy,
        status="pending",
        abbreviation_map_json=abbr_json,
        stats_json=_dumps(stats),
        options_json=_dumps(normalized),
    )
    session.add(run)
    session.flush()
    return serialize_run(run, session, project)


def list_runs(
    session: Session,
    document_id: int | None = None,
    project: ProjectState | None = None,
) -> list[dict[str, Any]]:
    stmt = select(ExtractionRun).order_by(ExtractionRun.id.desc())
    if document_id is not None:
        stmt = stmt.where(ExtractionRun.document_id == document_id)
    return [serialize_run(r, session, project) for r in session.scalars(stmt).all()]


def get_run(
    session: Session,
    run_id: int,
    project: ProjectState | None = None,
) -> dict[str, Any]:
    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise LookupError(f"Прогон не найден: {run_id}")
    return serialize_run(run, session, project)


def _step_by_id(recipe: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in recipe.get("steps") or []:
        if step.get("id") == step_id:
            return step
    raise LookupError(f"Шаг рецепта не найден: {step_id}")


GRAPH_SCOPES = frozenset({"accepted", "focus", "none"})
PHASE_MODES = frozenset({"both", "entities", "relations"})
ON_EMPTY_MODES = frozenset({"accept", "warn", "fail"})
RELATIONS_OVERLAY_INSTRUCTION = (
    "Не создавай заново Device/Compound; создай недостающие Layer/Material "
    "и рёбра к уже существующим label."
)


def _section_filters(recipe: dict[str, Any], step: dict[str, Any]) -> tuple[list[str], list[str]]:
    defaults = recipe.get("defaults") or {}
    include = list(step.get("section_include") or defaults.get("section_include") or [])
    exclude = list(step.get("section_exclude") or defaults.get("section_exclude") or [])
    return include, exclude


def _as_str_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} должен быть списком")
    return [str(item).strip() for item in value if str(item).strip()]


def _as_bool_option(value: Any, *, field: str) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{field} должен быть bool")
    return bool(value)


def normalize_run_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Нормализует оверлей прогона. Все поля необязательны."""
    if options is None or options == {}:
        return {}
    if not isinstance(options, dict):
        raise ValueError("options должен быть объектом")
    out: dict[str, Any] = {}

    for key in (
        "section_include",
        "section_exclude",
        "target_entities",
        "target_relations",
        "focus_labels",
    ):
        if options.get(key) is not None:
            out[key] = _as_str_list(options[key], field=key)

    if options.get("extra_instructions") is not None:
        text = str(options.get("extra_instructions") or "").strip()
        if text:
            out["extra_instructions"] = text

    if options.get("graph_scope") is not None:
        scope = str(options["graph_scope"]).strip().lower()
        if scope not in GRAPH_SCOPES:
            raise ValueError("graph_scope: ожидается accepted|focus|none")
        out["graph_scope"] = scope

    if options.get("phases") is not None:
        phases = str(options["phases"]).strip().lower()
        if phases not in PHASE_MODES:
            raise ValueError("phases: ожидается both|entities|relations")
        out["phases"] = phases

    if options.get("pack_chunks") is not None:
        out["pack_chunks"] = _as_bool_option(options["pack_chunks"], field="pack_chunks")

    if options.get("on_empty") is not None:
        on_empty = str(options["on_empty"]).strip().lower()
        if on_empty not in ON_EMPTY_MODES:
            raise ValueError("on_empty: ожидается accept|warn|fail")
        out["on_empty"] = on_empty

    if options.get("copy_abbreviations_from_run_id") is not None:
        try:
            out["copy_abbreviations_from_run_id"] = int(
                options["copy_abbreviations_from_run_id"]
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("copy_abbreviations_from_run_id должен быть числом") from exc

    if options.get("blind") is not None:
        out["blind"] = _as_bool_option(options["blind"], field="blind")

    return out


def is_blind_run(options: dict[str, Any] | None) -> bool:
    """Слепой прогон: эталон и accepted-граф этой статьи не видны модели."""
    if not options:
        return False
    return bool(options.get("blind"))


def _run_options(run: ExtractionRun | None) -> dict[str, Any]:
    if run is None:
        return {}
    raw = _loads(getattr(run, "options_json", None), {})
    if not isinstance(raw, dict):
        return {}
    try:
        return normalize_run_options(raw)
    except ValueError:
        return raw


def _overlay_section_filters(
    recipe: dict[str, Any],
    step: dict[str, Any],
    options: dict[str, Any],
) -> tuple[list[str], list[str]]:
    include, exclude = _section_filters(recipe, step)
    if options.get("section_include") is not None:
        include = list(options["section_include"])
    if options.get("section_exclude") is not None:
        exclude = list(options["section_exclude"])
    return include, exclude


def _overlay_step_targets(step: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    if options.get("target_entities") is None and options.get("target_relations") is None:
        return step
    step = dict(step)
    targets = dict(step.get("targets") or {})
    if options.get("target_entities") is not None:
        targets["entities"] = list(options["target_entities"])
    if options.get("target_relations") is not None:
        targets["relations"] = list(options["target_relations"])
    step["targets"] = targets
    return step


def _effective_phase(phase: str | None, options: dict[str, Any]) -> str | None:
    if phase:
        return phase
    mode = str(options.get("phases") or "both").strip().lower()
    if mode in {"entities", "relations"}:
        return mode
    return None


def _should_pack_chunks(options: dict[str, Any]) -> bool:
    return bool(options.get("pack_chunks", True))


def _entities_first_phases(step: dict[str, Any]) -> list[dict[str, Any]]:
    return list(
        step.get("phases")
        or [
            {"name": "entities", "prompt_template": "extract_entities"},
            {"name": "relations", "prompt_template": "extract_relations"},
        ]
    )


def _select_entities_first_phases(
    step: dict[str, Any],
    phase: str | None,
) -> list[dict[str, Any]]:
    phases = _entities_first_phases(step)
    if not phase:
        return phases
    selected = [item for item in phases if item.get("name") == phase]
    return selected or phases[:1]


def _overlay_extra_instructions(
    options: dict[str, Any],
    tmpl: str,
    extra: str = "",
    *,
    step: dict[str, Any] | None = None,
    local_llm: bool | None = None,
) -> str:
    parts: list[str] = []
    opt = str(options.get("extra_instructions") or "").strip()
    if opt:
        parts.append(opt)
    focus = [
        str(label).strip()
        for label in (options.get("focus_labels") or [])
        if str(label).strip()
    ]
    if focus:
        parts.append(
            "Обязательные якоря (уже существующие label, не создавай заново): "
            + ", ".join(focus)
        )
    if is_device_stack_step(step) and tmpl in {
        "extract_entities",
        "extract_relations",
        "one_shot_section",
        "iterative_next",
    }:
        # local_llm=None → облачная политика (без лимита 20); False тоже облачная.
        parts.append(stack_policy_instructions(local_llm=bool(local_llm)))
    if is_device_metrics_step(step) and tmpl in {
        "extract_entities",
        "extract_relations",
        "one_shot_section",
        "iterative_next",
    }:
        parts.append(metrics_policy_instructions())
    if is_luminescence_step(step) and tmpl in {
        "extract_entities",
        "extract_relations",
        "one_shot_section",
        "iterative_next",
    }:
        parts.append(luminescence_policy_instructions())
    if tmpl == "extract_relations":
        parts.append(RELATIONS_OVERLAY_INSTRUCTION)
    extra_s = (extra or "").strip()
    if extra_s:
        parts.append(extra_s)
    return "\n".join(parts)


def _accepted_plus_run_graph(
    graph: dict[str, Any],
    run_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        node
        for node in (graph.get("nodes") or [])
        if node.get("status") in {"accepted", "manual"}
        or (node.get("status") == "proposed" and node.get("run_id") == run_id)
    ]
    node_ids = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in (graph.get("edges") or [])
        if edge.get("source_node_id") in node_ids
        and edge.get("target_node_id") in node_ids
        and (
            edge.get("status") in {"accepted", "manual"}
            or (edge.get("status") == "proposed" and edge.get("run_id") == run_id)
        )
    ]
    return nodes, edges


def _focus_subgraph(
    graph: dict[str, Any],
    base_nodes: list[dict[str, Any]],
    base_edges: list[dict[str, Any]],
    focus_labels: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    focus = {
        str(label).strip().lower()
        for label in (focus_labels or [])
        if str(label).strip()
    }
    if not focus:
        return [], []
    all_nodes = list(graph.get("nodes") or [])
    id_to_node = {node["id"]: node for node in all_nodes}
    focus_ids = {
        node["id"]
        for node in all_nodes
        if str(node.get("label") or "").strip().lower() in focus
    }
    neighbor_ids: set[Any] = set()
    for edge in base_edges:
        source_id, target_id = edge.get("source_node_id"), edge.get("target_node_id")
        if source_id in focus_ids:
            neighbor_ids.add(target_id)
        if target_id in focus_ids:
            neighbor_ids.add(source_id)
    keep = focus_ids | neighbor_ids
    out_nodes: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for node in base_nodes:
        if node["id"] in keep and node["id"] not in seen:
            out_nodes.append(node)
            seen.add(node["id"])
    for node_id in focus_ids:
        if node_id not in seen and node_id in id_to_node:
            out_nodes.append(id_to_node[node_id])
            seen.add(node_id)
    out_ids = {node["id"] for node in out_nodes}
    out_edges = [
        edge
        for edge in base_edges
        if edge.get("source_node_id") in out_ids and edge.get("target_node_id") in out_ids
    ]
    return out_nodes, out_edges


def _existing_graph_for_prompt(
    graph: dict[str, Any],
    *,
    run_id: int | None,
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Граф в промпте. В blind — только узлы этого прогона."""
    if is_blind_run(options) and run_id is not None:
        return _run_only_graph(graph, run_id)
    scope = str(options.get("graph_scope") or "accepted").strip().lower()
    if scope not in GRAPH_SCOPES:
        scope = "accepted"
    if scope == "none":
        return [], []
    if run_id is not None:
        nodes, edges = _accepted_plus_run_graph(graph, run_id)
    else:
        nodes = list(graph.get("nodes") or [])
        edges = list(graph.get("edges") or [])
    if scope == "focus":
        return _focus_subgraph(graph, nodes, edges, options.get("focus_labels") or [])
    return nodes, edges


def _is_abbreviation_step(step: dict[str, Any]) -> bool:
    return (
        step.get("prompt_template") == "resolve_codes"
        or step.get("output_key") == "abbreviation_map"
    )


def _threshold(recipe: dict[str, Any]) -> float:
    defaults = recipe.get("defaults") or {}
    return float(defaults.get("quote_verify_threshold") or DEFAULT_QUOTE_THRESHOLD)


def preview_step_prompt(
    session: Session,
    project: ProjectState,
    *,
    document_id: int,
    recipe_id: str | None = None,
    step_id: str,
    run_id: int | None = None,
) -> dict[str, Any]:
    recipe = get_active_recipe_body(session, project, recipe_id)
    step = _step_by_id(recipe, step_id)
    run = None
    if run_id is not None:
        run = session.get(ExtractionRun, run_id)
        if run is None:
            raise LookupError(f"Прогон не найден: {run_id}")
    options = _run_options(run)
    step = _overlay_step_targets(step, options)
    schema_row = schema_service.get_active_schema_version(session)
    if schema_row is None:
        raise RuntimeError("Схема проекта не применена")
    schema = schema_service.schema_dict_from_db(schema_row)

    include, exclude = _overlay_section_filters(recipe, step, options)
    paragraphs, tables, captions = chunk_mod.load_document_blocks(
        session, document_id, section_include=include or None, section_exclude=exclude or None
    )
    context_size = 128000
    if run and run.llm_profile_id:
        try:
            context_size = llm_profiles.get_profile(run.llm_profile_id, project).context_size
        except Exception:
            pass
    elif project.settings.llm_profiles:
        context_size = project.settings.llm_profiles[0].context_size
    section_chunks = chunk_mod.chunk_by_sections(
        paragraphs,
        tables,
        captions,
        context_size=context_size,
        pack_chunks=_should_pack_chunks(options),
    )
    first = section_chunks[0] if section_chunks else {
        "section_text": "",
        "tables_md": "",
        "figure_captions": "",
    }
    graph = graph_service.get_graph(session, document_id)
    prompt_nodes, prompt_edges = _existing_graph_for_prompt(
        graph, run_id=run.id if run else None, options=options
    )
    abbr: list[dict[str, Any]] = []
    if run:
        abbr = _loads(run.abbreviation_map_json, [])

    golds = graph_service.list_gold_snapshots(session, document_id)
    gold_payload = {}
    if golds and not is_blind_run(options):
        gold_payload = graph_service.get_gold_snapshot(session, golds[0]["id"]).get("payload") or {}

    tmpl = step.get("prompt_template") or "extract_entities"
    if (step.get("strategy") or "") == "entities_first":
        selected = _select_entities_first_phases(step, _effective_phase(None, options))
        tmpl = (selected[0] or {}).get("prompt_template") or tmpl
    local_llm = False
    if run and run.llm_profile_id:
        try:
            local_llm = is_local_base_url(
                llm_profiles.get_profile(run.llm_profile_id, project).base_url
            )
        except Exception:
            local_llm = False
    elif project.settings.llm_profiles:
        local_llm = is_local_base_url(project.settings.llm_profiles[0].base_url)
    ctx = build_prompt_context(
        schema=schema,
        recipe=recipe,
        step=step,
        section_text=first.get("section_text") or "",
        tables_md=first.get("tables_md") or "",
        figure_captions=first.get("figure_captions") or "",
        abbreviation_map=abbr,
        existing_nodes=prompt_nodes,
        existing_edges=prompt_edges,
        gold_payload=gold_payload,
        extra_instructions=_overlay_extra_instructions(
            options, tmpl, step=step, local_llm=local_llm
        ),
    )
    prompt = render_prompt(recipe, tmpl, ctx)
    return {
        "step_id": step_id,
        "prompt_template": tmpl,
        "prompt": prompt,
        "context_keys": sorted(ctx.keys()),
        "chunks_count": len(section_chunks),
        "json_schema_preview": ctx.get("json_schema"),
    }


def run_step(
    session: Session,
    project: ProjectState,
    *,
    run_id: int,
    step_id: str | None = None,
    phase: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise LookupError(f"Прогон не найден: {run_id}")

    recipe = get_active_recipe_body(session, project, run.recipe_id)
    pipeline = [
        str(item)
        for item in (recipe.get("pipeline") or [s["id"] for s in recipe.get("steps") or []])
        if item
    ]
    step_id = step_id or run.current_step_id or (pipeline[0] if pipeline else None)
    if not step_id:
        raise RuntimeError("В рецепте нет шагов")
    step = _step_by_id(recipe, step_id)
    options = _run_options(run)
    step = _overlay_step_targets(step, options)
    phase = _effective_phase(phase, options)

    profile = llm_profiles.get_profile(run.llm_profile_id, project)
    schema_row = schema_service.get_active_schema_version(session)
    if schema_row is None:
        raise RuntimeError("Схема проекта не применена")
    schema = schema_service.schema_dict_from_db(schema_row)

    stats = _stats_dict(run)
    step_started_at = _now_iso()
    # Фиксируем running до LLM и до долгой нарезки чанков.
    _upsert_step_history(
        stats,
        pipeline,
        {
            "step_id": step_id,
            "status": "running",
            "started_at": step_started_at,
            "finished_at": None,
            "nodes": 0,
            "edges": 0,
            "abbreviations": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error": None,
        },
    )
    run.stats_json = _dumps(stats)
    run.status = "running"
    run.current_step_id = step_id
    # Коммит до LLM: иначе SQLite держит write-lock минутами и падают кнопки проверки.
    session.commit()
    session.refresh(run)

    token_base_prompt = _as_int(stats.get("prompt_tokens"))
    token_base_completion = _as_int(stats.get("completion_tokens"))
    abbr_raw = _loads(run.abbreviation_map_json, [])
    abbr: list[dict[str, Any]] = abbr_raw if isinstance(abbr_raw, list) else []
    abbr_before = len(abbr)
    created_nodes: list[dict[str, Any]] = []
    created_edges: list[dict[str, Any]] = []
    prompts_used: list[str] = []
    raw_outputs: list[Any] = []

    def _close_history(status: str, error: str | None) -> None:
        # Токены — дельта только этого запуска шага, не весь прогон.
        _upsert_step_history(
            stats,
            pipeline,
            {
                "step_id": step_id,
                "status": status,
                "started_at": step_started_at,
                "finished_at": _now_iso(),
                "nodes": len(created_nodes),
                "edges": len(created_edges),
                "abbreviations": max(0, len(abbr) - abbr_before),
                "prompt_tokens": max(0, _as_int(stats.get("prompt_tokens")) - token_base_prompt),
                "completion_tokens": max(
                    0, _as_int(stats.get("completion_tokens")) - token_base_completion
                ),
                "error": error,
            },
        )

    def _fail(exc: Exception) -> None:
        run.status = "failed"
        run.error_message = str(exc)[:1500]
        _close_history("failed", run.error_message)
        run.stats_json = _dumps(stats)
        # Коммит до повторного исключения: session_scope откатит только новую транзакцию.
        session.commit()

    try:
        include, exclude = _overlay_section_filters(recipe, step, options)
        paragraphs, tables, captions = chunk_mod.load_document_blocks(
            session,
            run.document_id,
            section_include=include or None,
            section_exclude=exclude or None,
        )
        all_blocks = paragraphs + tables + captions
        section_chunks = chunk_mod.chunk_by_sections(
            paragraphs,
            tables,
            captions,
            context_size=profile.context_size,
            pack_chunks=_should_pack_chunks(options),
        )
        if not section_chunks:
            section_chunks = [
                {
                    "section_type": "other",
                    "section_text": chunk_mod.full_document_text(session, run.document_id)[:20000],
                    "tables_md": "",
                    "figure_captions": "",
                    "blocks": all_blocks,
                }
            ]
        stats["chunks_total"] = len(section_chunks)
        stats["context_size"] = int(profile.context_size or 0)
        if section_chunks and section_chunks[0].get("merged_sections"):
            stats["merged_sections"] = section_chunks[0].get("merged_sections")

        threshold = _threshold(recipe)
        graph = graph_service.get_graph(session, run.document_id)
        golds = graph_service.list_gold_snapshots(session, run.document_id)
        gold_payload = {}
        if golds and not is_blind_run(options):
            gold_payload = (
                graph_service.get_gold_snapshot(session, golds[0]["id"]).get("payload") or {}
            )

        # Стратегия прогона перекрывает шаг, кроме словаря шифров.
        if _is_abbreviation_step(step):
            strategy = step.get("strategy") or run.strategy or "one_shot"
        else:
            strategy = run.strategy or step.get("strategy") or "entities_first"
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        raise

    def _call(tmpl: str, chunk: dict[str, Any], extra_instructions: str = "") -> dict[str, Any]:
        # Промпт: graph_scope (accepted / focus / none).
        # Apply-дедуп в _apply_llm_payload по-прежнему accepted + этот прогон.
        graph_now = graph_service.get_graph(session, run.document_id)
        prompt_nodes, prompt_edges = _existing_graph_for_prompt(
            graph_now, run_id=run.id, options=options
        )
        ctx = build_prompt_context(
            schema=schema,
            recipe=recipe,
            step=step,
            section_text=chunk.get("section_text") or "",
            tables_md=chunk.get("tables_md") or "",
            figure_captions=chunk.get("figure_captions") or "",
            abbreviation_map=abbr,
            existing_nodes=prompt_nodes,
            existing_edges=prompt_edges,
            gold_payload=gold_payload,
            prompt_template=tmpl,
            extra_instructions=_overlay_extra_instructions(
                options,
                tmpl,
                extra_instructions,
                step=step,
                local_llm=is_local_base_url(profile.base_url),
            ),
        )
        prompt = render_prompt(recipe, tmpl, ctx)
        prompts_used.append(prompt[:2000])
        if dry_run:
            return {"data": {"entities": [], "relations": [], "abbreviations": []}, "usage": {}}
        system = (
            "Ты извлекаешь структурированные данные. Отвечай только JSON. "
            "done:true ставь только если в ПЕРЕДАННОМ фрагменте текста нет новых "
            "сущностей целевых типов; не сдавайся заранее."
        )
        result = llm_client.structured_completion(
            profile,
            system_prompt=system,
            user_prompt=prompt,
        )
        usage = result.get("usage") or {}
        stats["prompt_tokens"] = int(stats.get("prompt_tokens") or 0) + int(
            usage.get("prompt_tokens") or 0
        )
        stats["completion_tokens"] = int(stats.get("completion_tokens") or 0) + int(
            usage.get("completion_tokens") or 0
        )
        stats["tokens"] = int(stats.get("prompt_tokens") or 0) + int(
            stats.get("completion_tokens") or 0
        )
        data = result.get("data") or {}
        # Один повтор, если модель вернула пусто при непустом тексте фрагмента
        section_len = len(chunk.get("section_text") or "")
        empty = not (data.get("entities") or data.get("relations") or data.get("abbreviations"))
        if (
            not dry_run
            and empty
            and section_len > 400
            and tmpl in {"extract_entities", "extract_relations", "one_shot_section", "iterative_next"}
        ):
            stats["empty_retries"] = int(stats.get("empty_retries") or 0) + 1
            retry = llm_client.structured_completion(
                profile,
                system_prompt=system,
                user_prompt=(
                    prompt
                    + "\n\nПредыдущий ответ был пустым. В этом фрагменте почти наверняка "
                    "есть факты. Извлеки хотя бы то, что явно названо (шифры соединений, "
                    "лиганды, свойства). done:true только если действительно ничего нет."
                ),
            )
            usage2 = retry.get("usage") or {}
            stats["prompt_tokens"] = int(stats.get("prompt_tokens") or 0) + int(
                usage2.get("prompt_tokens") or 0
            )
            stats["completion_tokens"] = int(stats.get("completion_tokens") or 0) + int(
                usage2.get("completion_tokens") or 0
            )
            stats["tokens"] = int(stats.get("prompt_tokens") or 0) + int(
                stats.get("completion_tokens") or 0
            )
            result = retry
        return result

    def _apply_chunk_payload(
        tmpl: str,
        chunk: dict[str, Any],
        *,
        extra_instructions: str = "",
    ) -> int:
        """Вызов LLM + apply. Возвращает число новых узлов."""
        result = _call(tmpl, chunk, extra_instructions=extra_instructions)
        data = result.get("data") or {}
        raw_outputs.append(data)
        if dry_run:
            return 0
        if not (data.get("entities") or data.get("relations")):
            stats["empty_chunks"] = int(stats.get("empty_chunks") or 0) + 1
        applied = _apply_llm_payload(
            session,
            run.document_id,
            run.id,
            data,
            chunk.get("blocks") or all_blocks,
            threshold=threshold,
            blind=is_blind_run(options),
        )
        created_nodes.extend(applied["nodes"])
        created_edges.extend(applied["edges"])
        stats["skipped_entities"] = int(stats.get("skipped_entities") or 0) + int(
            applied.get("skipped_entities") or 0
        )
        stats["skipped_relations"] = int(stats.get("skipped_relations") or 0) + int(
            applied.get("skipped_relations") or 0
        )
        stats["deduped_entities"] = int(stats.get("deduped_entities") or 0) + int(
            applied.get("deduped_entities") or 0
        )
        session.commit()
        return len(applied["nodes"])

    def _record_stack_audit() -> None:
        if not is_device_stack_step(step):
            return
        gaps = audit_incomplete_device_stacks(
            graph_service.get_graph(session, run.document_id),
            run_id=run.id,
        )
        stats["incomplete_device_stacks"] = gaps
        summary = format_incomplete_stacks_summary(gaps)
        if summary:
            stats["incomplete_device_stacks_summary"] = summary
        else:
            stats.pop("incomplete_device_stacks_summary", None)

    try:
        if step.get("prompt_template") == "resolve_codes" or step.get("output_key") == "abbreviation_map":
            # Первый шаг: словарь шифров (one chunk merge)
            merged_abbr: list[dict[str, Any]] = list(abbr)
            for chunk in section_chunks:
                result = _call("resolve_codes", chunk)
                data = result.get("data") or {}
                raw_outputs.append(data)
                for item in data.get("abbreviations") or []:
                    if isinstance(item, dict) and item.get("code"):
                        merged_abbr.append(item)
                # Пишем после каждого фрагмента: таймаут следующего не сотрёт уже полученное.
                seen: set[str] = set()
                uniq: list[dict[str, Any]] = []
                for item in merged_abbr:
                    code = str(item.get("code") or "").strip()
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    uniq.append(item)
                abbr = uniq
                run.abbreviation_map_json = _dumps(abbr)
                session.commit()

        elif strategy == "entities_first":
            selected = _select_entities_first_phases(step, phase)
            stack_step = is_device_stack_step(step)
            local_llm = is_local_base_url(profile.base_url)
            for ph in selected:
                tmpl = ph.get("prompt_template") or "extract_entities"
                phase_name = str(ph.get("name") or "")
                is_entities_phase = phase_name == "entities" or (
                    not phase_name and tmpl == "extract_entities"
                )
                for chunk in section_chunks:
                    _apply_chunk_payload(tmpl, chunk)

                # Добор неполных стеков после фазы entities
                if stack_step and is_entities_phase and not dry_run:
                    gaps = audit_incomplete_device_stacks(
                        graph_service.get_graph(session, run.document_id),
                        run_id=run.id,
                    )
                    if local_llm:
                        for _pass in range(1, MAX_LOCAL_STACK_PASSES):
                            if not gaps:
                                break
                            focus_instr = focus_incomplete_device_instruction(gaps[0])
                            nodes_before = len(created_nodes)
                            for chunk in section_chunks:
                                _apply_chunk_payload(
                                    tmpl, chunk, extra_instructions=focus_instr
                                )
                            if len(created_nodes) == nodes_before:
                                stats["stack_fill_stopped"] = "empty_pass"
                                break
                            stats["stack_fill_passes"] = int(
                                stats.get("stack_fill_passes") or 0
                            ) + 1
                            gaps = audit_incomplete_device_stacks(
                                graph_service.get_graph(session, run.document_id),
                                run_id=run.id,
                            )
                    elif gaps:
                        cloud_instr = focus_incomplete_devices_instruction(gaps)
                        for chunk in section_chunks:
                            _apply_chunk_payload(
                                tmpl, chunk, extra_instructions=cloud_instr
                            )
                        stats["stack_fill_passes"] = 1

            _record_stack_audit()

        elif strategy == "iterative":
            tmpl = step.get("prompt_template") or "iterative_next"
            # Один «следующий» объект: перебираем чанки, пустой done на одном
            # фрагменте НЕ останавливает обход остальных секций.
            found = False
            for chunk in section_chunks:
                result = _call(tmpl, chunk)
                data = result.get("data") or {}
                raw_outputs.append(data)
                if dry_run:
                    break
                if data.get("done") and not (data.get("entities") or []):
                    stats["empty_chunks"] = int(stats.get("empty_chunks") or 0) + 1
                    continue
                applied = _apply_llm_payload(
                    session,
                    run.document_id,
                    run.id,
                    data,
                    chunk.get("blocks") or all_blocks,
                    threshold=threshold,
                    blind=is_blind_run(options),
                )
                created_nodes.extend(applied["nodes"])
                created_edges.extend(applied["edges"])
                stats["skipped_entities"] = int(stats.get("skipped_entities") or 0) + int(
                    applied.get("skipped_entities") or 0
                )
                stats["skipped_relations"] = int(stats.get("skipped_relations") or 0) + int(
                    applied.get("skipped_relations") or 0
                )
                stats["deduped_entities"] = int(stats.get("deduped_entities") or 0) + int(
                    applied.get("deduped_entities") or 0
                )
                session.commit()
                if applied["nodes"]:
                    found = True
                    break
            stats["iterative_found"] = found
            stats["chunks_total"] = len(section_chunks)

        else:  # one_shot
            tmpl = step.get("prompt_template") or "one_shot_section"
            if tmpl in {"extract_entities", "extract_relations"} or not tmpl:
                tmpl = "one_shot_section"
            max_passes = int(step.get("max_passes") or 2)
            for pass_i in range(max_passes):
                for chunk in section_chunks:
                    result = _call(
                        tmpl,
                        chunk,
                        extra_instructions=f"Проход {pass_i + 1}/{max_passes}. Не дублируй уже найденное.",
                    )
                    data = result.get("data") or {}
                    raw_outputs.append(data)
                    if dry_run:
                        continue
                    if not (data.get("entities") or data.get("relations")):
                        stats["empty_chunks"] = int(stats.get("empty_chunks") or 0) + 1
                    applied = _apply_llm_payload(
                        session,
                        run.document_id,
                        run.id,
                        data,
                        chunk.get("blocks") or all_blocks,
                        threshold=threshold,
                        blind=is_blind_run(options),
                    )
                    created_nodes.extend(applied["nodes"])
                    created_edges.extend(applied["edges"])
                    stats["skipped_entities"] = int(stats.get("skipped_entities") or 0) + int(
                        applied.get("skipped_entities") or 0
                    )
                    stats["skipped_relations"] = int(stats.get("skipped_relations") or 0) + int(
                        applied.get("skipped_relations") or 0
                    )
                    stats["deduped_entities"] = int(stats.get("deduped_entities") or 0) + int(
                        applied.get("deduped_entities") or 0
                    )
                    # Промежуточный коммит: сущности видны в проверке до конца длинного шага
                    session.commit()
            # Один добор неполных стеков после one_shot
            if is_device_stack_step(step) and not dry_run:
                gaps = audit_incomplete_device_stacks(
                    graph_service.get_graph(session, run.document_id),
                    run_id=run.id,
                )
                if gaps:
                    local_llm = is_local_base_url(profile.base_url)
                    if local_llm:
                        focus_instr = focus_incomplete_device_instruction(gaps[0])
                    else:
                        focus_instr = focus_incomplete_devices_instruction(gaps)
                    for chunk in section_chunks:
                        _apply_chunk_payload(
                            tmpl, chunk, extra_instructions=focus_instr
                        )
                    stats["stack_fill_passes"] = 1
                _record_stack_audit()

        empty_result = not created_nodes and not created_edges
        on_empty = str(options.get("on_empty") or "accept").strip().lower()
        if (
            not dry_run
            and empty_result
            and not _is_abbreviation_step(step)
            and on_empty == "fail"
        ):
            deduped = _as_int(stats.get("deduped_entities"))
            retries = _as_int(stats.get("empty_retries"))
            run.status = "failed"
            run.error_message = (
                f"Пустой результат: 0 новых узлов и рёбер "
                f"(deduped_{deduped}, empty_retries={retries})"
            )
            _close_history("failed", run.error_message)
            run.stats_json = _dumps(stats)
            session.flush()
            return {
                "run": serialize_run(run, session, project),
                "step_id": step_id,
                "strategy": strategy,
                "dry_run": dry_run,
                "created_nodes": created_nodes,
                "created_edges": created_edges,
                "abbreviation_map": abbr,
                "prompts_preview": prompts_used[:3],
                "raw_outputs_count": len(raw_outputs),
            }
        if (
            not dry_run
            and empty_result
            and not _is_abbreviation_step(step)
            and on_empty == "warn"
        ):
            stats["empty_result"] = True

        _close_history("done", None)
        run.stats_json = _dumps(stats)
        run.status = "awaiting_review" if not dry_run else "completed"
        run.error_message = None
        # обновить статус документа (gold не сбрасываем)
        doc = graph_service.get_document(session, run.document_id)
        if not dry_run and created_nodes and doc.status != "gold":
            doc.status = "extracted"
        session.flush()

        return {
            "run": serialize_run(run, session, project),
            "step_id": step_id,
            "strategy": strategy,
            "dry_run": dry_run,
            "created_nodes": created_nodes,
            "created_edges": created_edges,
            "abbreviation_map": abbr,
            "prompts_preview": prompts_used[:3],
            "raw_outputs_count": len(raw_outputs),
        }
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        raise


def run_pipeline(
    session: Session,
    project: ProjectState,
    *,
    run_id: int,
    stop_after_step: str | None = None,
    ignore_human_review: bool = False,
) -> dict[str, Any]:
    """Прогон pipeline рецепта по порядку.

    По умолчанию останавливается после шага с human_review (UI).
    Для пакетных прогонов (M4) передайте ignore_human_review=True.
    После awaiting_review продолжает со следующего шага, не перезапуская словарь.
    """
    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise LookupError(f"Прогон не найден: {run_id}")
    recipe = get_active_recipe_body(session, project, run.recipe_id)
    pipeline = list(recipe.get("pipeline") or [])
    start_idx = 0
    if run.current_step_id and run.status == "awaiting_review":
        try:
            start_idx = pipeline.index(run.current_step_id) + 1
        except ValueError:
            start_idx = 0
    elif run.current_step_id and run.status == "failed":
        try:
            start_idx = pipeline.index(run.current_step_id)
        except ValueError:
            start_idx = 0
    if start_idx >= len(pipeline):
        raise RuntimeError(
            "Пайплайн уже пройден до конца. Создайте новый прогон или выберите шаг вручную."
        )
    results = []
    for sid in pipeline[start_idx:]:
        step_result = run_step(session, project, run_id=run_id, step_id=sid)
        results.append({"step_id": sid, "nodes": len(step_result["created_nodes"]), "edges": len(step_result["created_edges"])})
        refreshed = session.get(ExtractionRun, run_id)
        if refreshed is not None and refreshed.status == "failed":
            break
        if stop_after_step and sid == stop_after_step:
            break
        # После шага с human_review останавливаемся для UI
        step = _step_by_id(recipe, sid)
        if step.get("human_review", True) and not ignore_human_review:
            break
    return {"run": get_run(session, run_id, project), "steps": results}
