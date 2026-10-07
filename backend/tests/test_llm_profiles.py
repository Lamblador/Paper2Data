"""Редактирование LLM-профиля сохраняется в project.yaml."""

from paper2data.core.project import close_project, create_project, open_project
from paper2data.db.session import dispose_db
from paper2data.llm.profiles import add_profile, get_profile, update_profile


def test_update_profile_context_size(tmp_path):
    root = tmp_path / "proj"
    create_project(root, name="T")
    profile = add_profile(
        name="Local",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen",
        context_size=8192,
    )
    updated = update_profile(profile.id, context_size=32768, name="Local 32k")
    assert updated.context_size == 32768
    assert updated.name == "Local 32k"

    dispose_db()
    close_project()
    opened = open_project(root)
    again = get_profile(profile.id, opened)
    assert again.context_size == 32768
    assert again.name == "Local 32k"
    dispose_db()
    close_project()
