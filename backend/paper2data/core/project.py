"""Создание и открытие проекта-папки."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from paper2data.core.paths import recent_projects_path
from paper2data.db.session import init_project_db

PROJECT_YAML = "project.yaml"
DB_FILENAME = "paper2data.sqlite"
PAPERS_DIR = "papers"
CACHE_DIR = "cache"
EXPORTS_DIR = "exports"

_lock = threading.RLock()
_current_project: ProjectState | None = None


@dataclass
class LlmProfileConfig:
    id: str
    name: str
    base_url: str
    model: str
    secret_ref: str
    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    context_size: int = 128000
    intelligence_level: str = "medium"  # low | medium | high
    supports_json_mode: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "secret_ref": self.secret_ref,
            "price_in_per_1m": self.price_in_per_1m,
            "price_out_per_1m": self.price_out_per_1m,
            "context_size": self.context_size,
            "intelligence_level": self.intelligence_level,
            "supports_json_mode": self.supports_json_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmProfileConfig:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            base_url=str(data.get("base_url") or "https://api.openai.com/v1"),
            model=str(data.get("model") or ""),
            secret_ref=str(data.get("secret_ref") or data["id"]),
            price_in_per_1m=float(data.get("price_in_per_1m") or 0),
            price_out_per_1m=float(data.get("price_out_per_1m") or 0),
            context_size=int(data.get("context_size") or 128000),
            intelligence_level=str(data.get("intelligence_level") or "medium"),
            supports_json_mode=bool(data.get("supports_json_mode", True)),
        )


@dataclass
class ProjectSettings:
    name: str
    schema_template: str | None = None
    active_schema: str | None = None
    llm_profiles: list[LlmProfileConfig] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema_template": self.schema_template,
            "active_schema": self.active_schema,
            "llm_profiles": [p.to_dict() for p in self.llm_profiles],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectSettings:
        profiles = [
            LlmProfileConfig.from_dict(p) for p in (data.get("llm_profiles") or [])
        ]
        return cls(
            name=str(data.get("name") or "Без названия"),
            schema_template=data.get("schema_template"),
            active_schema=data.get("active_schema"),
            llm_profiles=profiles,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class ProjectState:
    root: Path
    settings: ProjectSettings

    @property
    def yaml_path(self) -> Path:
        return self.root / PROJECT_YAML

    @property
    def db_path(self) -> Path:
        return self.root / DB_FILENAME

    @property
    def papers_dir(self) -> Path:
        return self.root / PAPERS_DIR

    @property
    def cache_dir(self) -> Path:
        return self.root / CACHE_DIR

    @property
    def exports_dir(self) -> Path:
        return self.root / EXPORTS_DIR


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / PAPERS_DIR).mkdir(exist_ok=True)
    (root / CACHE_DIR).mkdir(exist_ok=True)
    (root / EXPORTS_DIR).mkdir(exist_ok=True)


def _default_settings(name: str) -> ProjectSettings:
    now = _utc_now()
    return ProjectSettings(name=name, created_at=now, updated_at=now)


def save_project_settings(project: ProjectState) -> None:
    project.settings.updated_at = _utc_now()
    with project.yaml_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            project.settings.to_dict(),
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def load_project_settings(root: Path) -> ProjectSettings:
    path = root / PROJECT_YAML
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("project.yaml имеет неверный формат")
    return ProjectSettings.from_dict(data)


def _remember_project(root: Path, name: str) -> None:
    path = recent_projects_path()
    items: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or []
        if isinstance(loaded, list):
            items = [x for x in loaded if isinstance(x, dict)]

    root_str = str(root.resolve())
    items = [x for x in items if x.get("path") != root_str]
    items.insert(0, {"path": root_str, "name": name, "opened_at": _utc_now()})
    items = items[:20]
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(items, fh, allow_unicode=True, sort_keys=False)


def list_recent_projects() -> list[dict[str, str]]:
    path = recent_projects_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or []
    if not isinstance(loaded, list):
        return []
    result: list[dict[str, str]] = []
    for item in loaded:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        p = Path(str(item["path"]))
        result.append(
            {
                "path": str(p),
                "name": str(item.get("name") or p.name),
                "opened_at": str(item.get("opened_at") or ""),
                "exists": str(p.exists() and (p / PROJECT_YAML).exists()).lower(),
            }
        )
    return result


def get_current_project() -> ProjectState | None:
    with _lock:
        return _current_project


def require_project() -> ProjectState:
    project = get_current_project()
    if project is None:
        raise RuntimeError("Проект не открыт")
    return project


def create_project(root: Path | str, name: str | None = None) -> ProjectState:
    global _current_project
    root = Path(root).expanduser().resolve()
    _ensure_layout(root)

    yaml_path = root / PROJECT_YAML
    if yaml_path.exists():
        raise FileExistsError(f"В папке уже есть проект: {yaml_path}")

    settings = _default_settings(name or root.name)
    project = ProjectState(root=root, settings=settings)
    save_project_settings(project)
    init_project_db(project.db_path)
    _seed_figure_classes()
    _remember_project(root, settings.name)

    with _lock:
        _current_project = project
    return project


def open_project(root: Path | str) -> ProjectState:
    global _current_project
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {root}")

    yaml_path = root / PROJECT_YAML
    if not yaml_path.exists():
        raise FileNotFoundError(f"Не найден project.yaml в {root}")

    _ensure_layout(root)
    settings = load_project_settings(root)
    project = ProjectState(root=root, settings=settings)
    init_project_db(project.db_path)
    _seed_figure_classes()
    _remember_project(root, settings.name)

    with _lock:
        _current_project = project
    return project


def _seed_figure_classes() -> None:
    """Идемпотентный seed базовых классов рисунков (M5)."""
    try:
        from paper2data.db.session import session_scope
        from paper2data.figures.classes import seed_builtin_classes

        with session_scope() as session:
            seed_builtin_classes(session)
    except Exception:  # noqa: BLE001
        pass


def close_project() -> None:
    global _current_project
    with _lock:
        _current_project = None


def pick_folder_dialog(title: str = "Выберите папку проекта") -> str | None:
    """Системный диалог выбора папки (tkinter)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title=title, mustexist=False)
    finally:
        root.destroy()
    return selected or None
