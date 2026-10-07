"""История чата ассистента по статье.

Revision ID: 0007_assistant_thread
Revises: 0006_m4_corpus
Create Date: 2026-09-28 13:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_assistant_thread"
down_revision: Union[str, None] = "0006_m4_corpus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("messages_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("events_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pending_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_id", name="uq_assistant_thread_document"),
    )
    op.create_index(
        "ix_assistant_threads_document_id", "assistant_threads", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_threads_document_id", table_name="assistant_threads")
    op.drop_table("assistant_threads")
