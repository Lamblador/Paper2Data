"""M5: FigureClass + Figure.

Revision ID: 0005_m5_figures
Revises: 0004_m3_extraction
Create Date: 2026-03-28 15:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_m5_figures"
down_revision: Union[str, None] = "0004_m3_extraction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "figure_classes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_figure_class_slug"),
    )

    op.create_table(
        "figures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="embedded"),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("figure_classes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("manual_label", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uncertain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_figures_document_id", "figures", ["document_id"])
    op.create_index("ix_figures_class_id", "figures", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_figures_class_id", table_name="figures")
    op.drop_index("ix_figures_document_id", table_name="figures")
    op.drop_table("figures")
    op.drop_table("figure_classes")
