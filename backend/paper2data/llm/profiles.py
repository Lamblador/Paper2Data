"""Управление LLM-профилями в настройках проекта."""

from __future__ import annotations

import re
import uuid
from typing import Any

from paper2data.core.project import (
    LlmProfileConfig,
    ProjectState,
    require_project,
    save_project_settings,
)
from paper2data.llm import secrets as secrets_store


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "profile"


def list_profiles(project: ProjectState | None = None) -> list[dict[str, Any]]:
    project = project or require_project()
    result: list[dict[str, Any]] = []
    for profile in project.settings.llm_profiles:
        item = profile.to_dict()
        item["has_api_key"] = secrets_store.has_secret(profile.secret_ref)
        item.pop("secret_ref", None)
        result.append(item)
    return result


def get_profile(profile_id: str, project: ProjectState | None = None) -> LlmProfileConfig:
    project = project or require_project()
    for profile in project.settings.llm_profiles:
        if profile.id == profile_id:
            return profile
    raise KeyError(f"Профиль не найден: {profile_id}")


def add_profile(
    *,
    name: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    price_in_per_1m: float = 0.0,
    price_out_per_1m: float = 0.0,
    context_size: int = 128000,
    intelligence_level: str = "medium",
    supports_json_mode: bool = True,
    project: ProjectState | None = None,
) -> LlmProfileConfig:
    project = project or require_project()
    profile_id = f"{_slugify(name)}-{uuid.uuid4().hex[:8]}"
    secret_ref = profile_id
    profile = LlmProfileConfig(
        id=profile_id,
        name=name.strip() or profile_id,
        base_url=base_url.rstrip("/"),
        model=model.strip(),
        secret_ref=secret_ref,
        price_in_per_1m=price_in_per_1m,
        price_out_per_1m=price_out_per_1m,
        context_size=context_size,
        intelligence_level=intelligence_level,
        supports_json_mode=supports_json_mode,
    )
    if api_key:
        secrets_store.set_secret(secret_ref, api_key.strip())
    project.settings.llm_profiles.append(profile)
    save_project_settings(project)
    return profile


def update_profile(
    profile_id: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    price_in_per_1m: float | None = None,
    price_out_per_1m: float | None = None,
    context_size: int | None = None,
    intelligence_level: str | None = None,
    supports_json_mode: bool | None = None,
    project: ProjectState | None = None,
) -> LlmProfileConfig:
    project = project or require_project()
    profile = get_profile(profile_id, project)
    if name is not None:
        profile.name = name.strip() or profile.name
    if base_url is not None:
        profile.base_url = base_url.rstrip("/")
    if model is not None:
        profile.model = model.strip()
    if price_in_per_1m is not None:
        profile.price_in_per_1m = price_in_per_1m
    if price_out_per_1m is not None:
        profile.price_out_per_1m = price_out_per_1m
    if context_size is not None:
        profile.context_size = context_size
    if intelligence_level is not None:
        profile.intelligence_level = intelligence_level
    if supports_json_mode is not None:
        profile.supports_json_mode = supports_json_mode
    if api_key is not None and api_key.strip():
        secrets_store.set_secret(profile.secret_ref, api_key.strip())
    save_project_settings(project)
    return profile


def delete_profile(profile_id: str, project: ProjectState | None = None) -> None:
    project = project or require_project()
    profile = get_profile(profile_id, project)
    project.settings.llm_profiles = [
        p for p in project.settings.llm_profiles if p.id != profile_id
    ]
    secrets_store.delete_secret(profile.secret_ref)
    save_project_settings(project)
