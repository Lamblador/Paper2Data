"""Журнал ассистента сохраняется вместе со статьёй."""

from paper2data.assistant.service import (
    describe_tool,
    get_thread,
    reject_mutations,
    save_thread,
)
from paper2data.core.project import close_project, create_project, open_project
from paper2data.db.session import dispose_db, session_scope
from paper2data.graph.service import create_document


def test_describe_tool_search_mentions_hits():
    text = describe_tool(
        "search_document",
        {"query": "DBM"},
        {
            "ok": True,
            "query": "DBM",
            "count": 1,
            "hits": [{"page": 3, "block_id": 12, "snippet": "complex with DBM"}],
        },
    )
    assert "DBM" in text
    assert "блок #12" in text


def test_thread_survives_reopen_and_reject(tmp_path):
    root = tmp_path / "proj"
    create_project(root, name="T")
    with session_scope() as session:
        doc = create_document(session, title="Статья")
        doc_id = doc["id"]
        save_thread(
            session,
            doc_id,
            messages=[{"role": "user", "content": "найди DBM"}],
            events=[
                {"id": "evt_user", "kind": "user", "content": "найди DBM"},
                {
                    "id": "evt_tool",
                    "kind": "tool",
                    "tool": "search_document",
                    "content": "Искал в статье «DBM»",
                },
            ],
            pending=[
                {
                    "id": "mut_1",
                    "action": "create_node",
                    "summary": "Создать узел «Compound»",
                    "args": {},
                }
            ],
        )

    dispose_db()
    close_project()
    open_project(root)
    with session_scope() as session:
        thread = get_thread(session, doc_id)
        assert [e["kind"] for e in thread["events"]] == ["user", "tool"]
        assert thread["pending_mutations"][0]["id"] == "mut_1"
        rejected = reject_mutations(session, document_id=doc_id, mutation_ids=["mut_1"])
        assert rejected["pending_mutations"] == []
        assert rejected["events"][-1]["status"] == "rejected"
        assert "Отклонено" in rejected["events"][-1]["content"]

    dispose_db()
    close_project()
