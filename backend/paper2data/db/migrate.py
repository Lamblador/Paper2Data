"""Обёртка над Alembic для БД проекта."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.sql.schema import Column


def _alembic_root() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic"


def make_alembic_config(db_path: Path) -> Config:
    cfg = Config()
    alembic_dir = _alembic_root()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.resolve().as_posix()}")
    return cfg


def ensure_migrations(engine: Engine, db_path: Path) -> None:
    """Применить миграции или создать схему и проставить head."""
    from paper2data.db.models import Base

    alembic_dir = _alembic_root()
    if not (alembic_dir / "env.py").exists():
        Base.metadata.create_all(engine)
        _reconcile_missing_columns(engine)
        return

    cfg = make_alembic_config(db_path)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current = context.get_current_revision()
        tables = inspect(conn).get_table_names()

    try:
        if current is None:
            if "app_meta" in tables:
                # Старая БД без отметки или после create_all — дотягиваем модели и stamp
                Base.metadata.create_all(engine)
                if head:
                    command.stamp(cfg, head)
            else:
                command.upgrade(cfg, "head")
        elif current != head:
            try:
                command.upgrade(cfg, "head")
            except (OperationalError, DatabaseError) as exc:
                # Модели уже накатили часть колонок через create_all, а alembic отстаёт.
                message = str(exc).lower()
                if "duplicate column" not in message and "already exists" not in message:
                    raise
                if head:
                    command.stamp(cfg, head)
    finally:
        # create_all не добавляет колонки в уже существующие таблицы.
        # Если ALTER оборвался, недостающие поля всё равно нужно дописать.
        Base.metadata.create_all(engine)
        _reconcile_missing_columns(engine)


def _not_null_default_sql(col: Column, dialect) -> str:
    """Литерал DEFAULT для ADD COLUMN NOT NULL в SQLite."""
    server_default = col.server_default
    if server_default is not None:
        arg = server_default.arg
        try:
            if hasattr(arg, "compile"):
                return str(arg.compile(dialect=dialect))
        except Exception:  # noqa: BLE001
            pass
        if isinstance(arg, str):
            return arg

    default = col.default
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return repr(value)

    type_name = type(col.type).__name__.lower()
    if any(token in type_name for token in ("int", "float", "bool", "numeric")):
        return "0"
    if "date" in type_name or "time" in type_name:
        return "CURRENT_TIMESTAMP"
    return "''"


def _reconcile_missing_columns(engine: Engine) -> None:
    """Добавить колонки моделей, которых нет в таблицах SQLite."""
    from paper2data.db.models import Base

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    dialect = engine.dialect
    quote = dialect.identifier_preparer.quote
    statements: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        have = {col["name"] for col in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            type_sql = col.type.compile(dialect=dialect)
            clause = (
                f"ALTER TABLE {quote(table.name)} "
                f"ADD COLUMN {quote(col.name)} {type_sql}"
            )
            if not col.nullable:
                clause += f" NOT NULL DEFAULT {_not_null_default_sql(col, dialect)}"
            statements.append(clause)

    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def stamp_if_needed(engine: Engine, db_path: Path) -> None:
    """Совместимость с M0: делегирует в ensure_migrations."""
    ensure_migrations(engine, db_path)


def upgrade_head(db_path: Path) -> None:
    cfg = make_alembic_config(db_path)
    command.upgrade(cfg, "head")
