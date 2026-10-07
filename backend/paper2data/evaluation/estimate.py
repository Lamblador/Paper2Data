"""Оценка токенов/стоимости перед пакетным прогоном."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from paper2data.core.project import ProjectState
from paper2data.db.models import ExtractionRun, GoldSnapshot
from paper2data.evaluation.cost import (
    average_output_tokens_from_runs,
    count_tokens,
    estimate_batch_cost,
)
from paper2data.llm import profiles as llm_profiles


def _loads(text: str | None, default: Any) -> Any:
    import json

    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def estimate_corpus_cost(
    session: Session,
    project: ProjectState,
    *,
    document_ids: list[int],
    llm_profile_ids: list[str],
    recipe_id: str | None = None,
) -> dict[str, Any]:
    """Считает токены промптов+чанков по шагам рецепта × документы × профили."""
    from paper2data.extraction import engine as extraction_engine

    recipe = extraction_engine.get_active_recipe_body(session, project, recipe_id)
    steps = list(recipe.get("steps") or [])
    step_ids = [s["id"] for s in steps if s.get("id")]
    pipeline = list(recipe.get("pipeline") or step_ids)
    if not pipeline:
        pipeline = step_ids

    prompt_tokens_by_doc: dict[int, int] = {}
    per_doc_detail: dict[str, Any] = {}

    for doc_id in document_ids:
        total = 0
        step_tokens: dict[str, int] = {}
        for sid in pipeline:
            try:
                preview = extraction_engine.preview_step_prompt(
                    session,
                    project,
                    document_id=doc_id,
                    recipe_id=recipe.get("id") or recipe_id,
                    step_id=sid,
                )
            except Exception as exc:  # noqa: BLE001
                step_tokens[sid] = 0
                per_doc_detail.setdefault(str(doc_id), {})[sid] = {"error": str(exc)}
                continue
            texts: list[str] = []
            if preview.get("system"):
                texts.append(str(preview["system"]))
            if preview.get("user"):
                texts.append(str(preview["user"]))
            if preview.get("prompt"):
                texts.append(str(preview["prompt"]))
            for msg in preview.get("messages") or []:
                texts.append(str(msg.get("content") or ""))
            if preview.get("section_text"):
                texts.append(str(preview["section_text"]))
            tok = sum(count_tokens(t) for t in texts)
            if tok == 0 and preview.get("rendered"):
                tok = count_tokens(str(preview["rendered"]))
            step_tokens[sid] = tok
            total += tok
        prompt_tokens_by_doc[doc_id] = total
        per_doc_detail[str(doc_id)] = {"steps": step_tokens, "tokens_in": total}

    gold_doc_ids = set(
        session.scalars(select(GoldSnapshot.document_id).distinct()).all()
    )
    stats_list: list[dict[str, Any]] = []
    for run in session.scalars(
        select(ExtractionRun).where(ExtractionRun.document_id.in_(gold_doc_ids or [-1]))
    ).all():
        stats_list.append(_loads(run.stats_json, {}))
    avg_out = average_output_tokens_from_runs(stats_list)

    profiles_cfg = []
    for pid in llm_profile_ids:
        try:
            p = llm_profiles.get_profile(pid, project)
            profiles_cfg.append(p.to_dict())
        except KeyError:
            profiles_cfg.append(
                {
                    "id": pid,
                    "name": pid,
                    "price_in_per_1m": 0.0,
                    "price_out_per_1m": 0.0,
                }
            )

    estimate = estimate_batch_cost(
        document_ids=document_ids,
        profiles=profiles_cfg,
        steps_per_document=max(1, len(pipeline)),
        prompt_tokens_by_doc=prompt_tokens_by_doc,
        avg_output_tokens_per_run=avg_out,
    )
    estimate["recipe_id"] = recipe.get("id")
    estimate["pipeline_steps"] = pipeline
    estimate["per_document"] = per_doc_detail
    return estimate
