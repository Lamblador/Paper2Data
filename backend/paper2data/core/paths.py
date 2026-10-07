"""Пути пользовательских данных Paper2Data."""

from __future__ import annotations

from pathlib import Path


APP_DIR_NAME = ".paper2data"


def home_app_dir() -> Path:
    """Каталог пользовательских данных: ~/.paper2data."""
    path = Path.home() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def secrets_path() -> Path:
    """Файл с секретами LLM (API-ключи)."""
    return home_app_dir() / "secrets"


def recent_projects_path() -> Path:
    """Список недавно открытых проектов."""
    return home_app_dir() / "recent_projects.yaml"
