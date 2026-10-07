"""M4: evaluations + расширенный jobs.

Revision ID: 0006_m4_corpus
Revises: 0005_m5_figures
Create Date: 2026-03-28 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_m4_corpus"
down_revision: Union[str, None] = "0005_m5_figures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "extraction_run_id",
            sa.Integer(),
            sa.ForeignKey("extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gold_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("gold_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1", sa.Float(), nullable=True),
        sa.Column("attribute_accuracy", sa.Float(), nullable=True),
        sa.Column("edge_f1", sa.Float(), nullable=True),
        sa.Column("verified_quote_rate", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_evaluations_extraction_run_id", "evaluations", ["extraction_run_id"])
    op.create_index("ix_evaluations_gold_snapshot_id", "evaluations", ["gold_snapshot_id"])
    op.create_index("ix_evaluations_document_id", "evaluations", ["document_id"])

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("progress", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("message", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("error_message")
        batch.drop_column("result_json")
        batch.drop_column("message")
        batch.drop_column("progress")

    op.drop_index("ix_evaluations_document_id", table_name="evaluations")
    op.drop_index("ix_evaluations_gold_snapshot_id", table_name="evaluations")
    op.drop_index("ix_evaluations_extraction_run_id", table_name="evaluations")
    op.drop_table("evaluations")
