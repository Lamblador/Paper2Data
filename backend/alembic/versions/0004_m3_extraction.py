"""M3: recipes + extraction_runs.

Revision ID: 0004_m3_extraction
Revises: 0003_m1_ingest
Create Date: 2026-03-28 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_m3_extraction"
down_revision: Union[str, None] = "0003_m1_ingest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipe_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("schema_id", sa.String(length=128), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("yaml_body", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recipes_recipe_id", "recipes", ["recipe_id"])

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipe_db_id",
            sa.Integer(),
            sa.ForeignKey("recipes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipe_id", sa.String(length=128), nullable=False),
        sa.Column("llm_profile_id", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step_id", sa.String(length=128), nullable=True),
        sa.Column("abbreviation_map_json", sa.Text(), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])
    op.create_index("ix_extraction_runs_recipe_db_id", "extraction_runs", ["recipe_db_id"])


def downgrade() -> None:
    op.drop_index("ix_extraction_runs_recipe_db_id", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_index("ix_recipes_recipe_id", table_name="recipes")
    op.drop_table("recipes")
