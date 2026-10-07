"""Догонка колонок, если БД stamped на head без ALTER-миграций."""

from sqlalchemy import create_engine, inspect, text

from paper2data.db.migrate import ensure_migrations
from paper2data.db.session import dispose_db


def test_reconcile_adds_columns_missing_after_stamp(tmp_path):
    db_path = tmp_path / "paper2data.sqlite"
    engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE app_meta ("
                "key VARCHAR(128) PRIMARY KEY, "
                "value TEXT NOT NULL, "
                "updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_meta (key, value) VALUES ('schema_version', '1')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE blocks ("
                "id INTEGER PRIMARY KEY, "
                "document_id INTEGER NOT NULL, "
                "section_id INTEGER, "
                "kind VARCHAR(64) NOT NULL DEFAULT 'paragraph', "
                "text TEXT NOT NULL DEFAULT '', "
                "page INTEGER, "
                "bbox_json TEXT, "
                "order_index INTEGER NOT NULL DEFAULT 0, "
                "meta_json TEXT NOT NULL DEFAULT '{}')"
            )
        )
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0006_m4_corpus')")
        )

    ensure_migrations(engine, db_path)
    cols = {col["name"] for col in inspect(engine).get_columns("blocks")}
    assert "page_width" in cols
    assert "page_height" in cols
    engine.dispose()
    dispose_db()


def test_reconcile_when_upgrade_hits_existing_column(tmp_path):
    db_path = tmp_path / "paper2data.sqlite"
    engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE app_meta ("
                "key VARCHAR(128) PRIMARY KEY, value TEXT NOT NULL, updated_at DATETIME)"
            )
        )
        conn.execute(
            text("INSERT INTO app_meta (key, value) VALUES ('schema_version', '1')")
        )
        conn.execute(
            text(
                "CREATE TABLE documents ("
                "id INTEGER PRIMARY KEY, "
                "title VARCHAR(512) NOT NULL DEFAULT '', "
                "status VARCHAR(32) NOT NULL DEFAULT 'indexed', "
                "source_path VARCHAR(1024), "
                "source_stem VARCHAR(512) NOT NULL DEFAULT '', "
                "meta_json TEXT NOT NULL DEFAULT '{}', "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE blocks ("
                "id INTEGER PRIMARY KEY, "
                "document_id INTEGER NOT NULL, "
                "section_id INTEGER, "
                "kind VARCHAR(64) NOT NULL DEFAULT 'paragraph', "
                "text TEXT NOT NULL DEFAULT '', "
                "page INTEGER, "
                "bbox_json TEXT, "
                "order_index INTEGER NOT NULL DEFAULT 0, "
                "meta_json TEXT NOT NULL DEFAULT '{}')"
            )
        )
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) VALUES ('0002_m2_schema_graph')"
            )
        )

    ensure_migrations(engine, db_path)
    cols = {col["name"] for col in inspect(engine).get_columns("blocks")}
    assert "page_width" in cols
    assert "page_height" in cols
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0006_m4_corpus"
    engine.dispose()
    dispose_db()
