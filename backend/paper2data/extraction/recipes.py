"""Загрузка / сохранение YAML-рецептов извлечения."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from paper2data.schema.loader import templates_root

REQUIRED_TOP_KEYS = ("version", "id", "name", "kind", "schema_id", "steps")
VALID_STRATEGIES = {"iterative", "entities_first", "one_shot"}


def recipes_templates_root() -> Path:
    return templates_root() / "recipes"


def project_recipes_dir(project_root: Path) -> Path:
    path = project_root / "recipes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def recipe_to_yaml(recipe: dict[str, Any]) -> str:
    return yaml.safe_dump(
        recipe,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def parse_recipe_yaml(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Рецепт должен быть YAML-объектом")
    return validate_recipe(data)


def validate_recipe(data: dict[str, Any]) -> dict[str, Any]:
    recipe = deepcopy(data)
    kind = str(recipe.get("kind") or "recipe")
    if kind != "recipe":
        raise ValueError(f"Ожидался kind: recipe, получено: {kind}")
    for key in REQUIRED_TOP_KEYS:
        if key == "kind":
            continue
        if key not in recipe or recipe[key] in (None, ""):
            raise ValueError(f"В рецепте отсутствует обязательное поле: {key}")
    recipe["kind"] = "recipe"
    recipe["id"] = str(recipe["id"])
    recipe["name"] = str(recipe["name"])
    recipe["schema_id"] = str(recipe["schema_id"])
    recipe["version"] = str(recipe.get("version") or "1.0")
    recipe["description"] = str(recipe.get("description") or "")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Рецепт должен содержать непустой список steps")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Шаг #{i} должен быть объектом")
        if not step.get("id"):
            raise ValueError(f"Шаг #{i} без id")
        strategy = step.get("strategy") or (recipe.get("defaults") or {}).get("strategy")
        if strategy and strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"Шаг {step['id']}: неизвестная стратегия {strategy}. "
                f"Допустимо: {sorted(VALID_STRATEGIES)}"
            )
        step["id"] = str(step["id"])
        step["name"] = str(step.get("name") or step["id"])
        if strategy:
            step["strategy"] = strategy
    recipe["steps"] = steps
    if "defaults" not in recipe or not isinstance(recipe["defaults"], dict):
        recipe["defaults"] = {
            "strategy": "entities_first",
            "require_quote": True,
            "quote_verify_threshold": 90,
        }
    if "prompt_templates" not in recipe or not isinstance(recipe["prompt_templates"], dict):
        recipe["prompt_templates"] = {}
    if "pipeline" not in recipe:
        recipe["pipeline"] = [s["id"] for s in steps if s.get("enabled", True)]
    return recipe


def load_recipe_file(path: Path) -> dict[str, Any]:
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ValueError(f"Некорректный рецепт: {path}")
    recipe = validate_recipe(raw)
    recipe["_source_path"] = str(path)
    return recipe


def list_bundled_recipes() -> list[dict[str, Any]]:
    root = recipes_templates_root()
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            recipe = load_recipe_file(path)
        except ValueError:
            continue
        result.append(
            {
                "id": recipe["id"],
                "name": recipe["name"],
                "version": recipe["version"],
                "schema_id": recipe["schema_id"],
                "description": recipe.get("description") or "",
                "steps_count": len(recipe.get("steps") or []),
                "source": "bundled",
                "path": str(path),
            }
        )
    return result


def list_project_recipe_files(project_root: Path) -> list[dict[str, Any]]:
    root = project_recipes_dir(project_root)
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            recipe = load_recipe_file(path)
        except ValueError:
            continue
        result.append(
            {
                "id": recipe["id"],
                "name": recipe["name"],
                "version": recipe["version"],
                "schema_id": recipe["schema_id"],
                "description": recipe.get("description") or "",
                "steps_count": len(recipe.get("steps") or []),
                "source": "project",
                "path": str(path),
            }
        )
    return result


def save_recipe_to_project(project_root: Path, recipe: dict[str, Any]) -> Path:
    validated = validate_recipe(recipe)
    path = project_recipes_dir(project_root) / f"{validated['id']}.yaml"
    path.write_text(recipe_to_yaml(validated), encoding="utf-8")
    return path


def resolve_recipe(
    recipe_id: str,
    *,
    project_root: Path | None = None,
    yaml_text: str | None = None,
) -> dict[str, Any]:
    """Приоритет: явный YAML → рецепт проекта → bundled template."""
    if yaml_text:
        return parse_recipe_yaml(yaml_text)
    if project_root is not None:
        candidate = project_recipes_dir(project_root) / f"{recipe_id}.yaml"
        if candidate.is_file():
            return load_recipe_file(candidate)
    bundled = recipes_templates_root() / f"{recipe_id}.yaml"
    if bundled.is_file():
        return load_recipe_file(bundled)
    # fallback: any bundled with matching id
    for path in recipes_templates_root().glob("*.yaml"):
        try:
            r = load_recipe_file(path)
        except ValueError:
            continue
        if r["id"] == recipe_id:
            return r
    raise FileNotFoundError(f"Рецепт не найден: {recipe_id}")


def default_strategy_for_intelligence(level: str) -> str:
    """Стратегия по умолчанию из уровня интеллекта LLM-профиля."""
    normalized = (level or "medium").strip().lower()
    if normalized in {"high", "strong", "sota"}:
        return "one_shot"
    if normalized in {"low", "small", "weak"}:
        return "iterative"
    return "entities_first"
