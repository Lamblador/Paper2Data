"""Базовый smoke-тест импортов и создания проекта."""

from __future__ import annotations

from pathlib import Path

from paper2data.api.app import create_app
from paper2data.core.project import create_project, open_project
from paper2data.db.session import check_db_alive, dispose_db


def test_create_app():
    app = create_app()
    assert app.title == "Paper2Data"


def test_create_and_open_project(tmp_path: Path):
    root = tmp_path / "demo"
    project = create_project(root, name="Демо")
    assert project.yaml_path.exists()
    assert project.db_path.exists()
    assert project.papers_dir.is_dir()
    assert check_db_alive()

    dispose_db()
    opened = open_project(root)
    assert opened.settings.name == "Демо"
    assert check_db_alive()
    dispose_db()
