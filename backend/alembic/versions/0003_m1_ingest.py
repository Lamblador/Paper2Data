"""M1: DocFile, Reference, ESI hints, page size on blocks.

Revision ID: 0003_m1_ingest
Revises: 0002_m2_schema_graph
Create Date: 2026-03-28 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_m1_ingest"
down_revision: Union[str, None] = "0002_m2_schema_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("source_stem", sa.String(length=512), nullable=False, server_default=""))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("esi_hints_json", sa.Text(), nullable=False, server_default="[]"))

    op.create_table(
        "doc_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_doc_files_document_id", "doc_files", ["document_id"])

    with op.batch_alter_table("sections") as batch:
        batch.add_column(sa.Column("doc_file_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_sections_doc_file_id",
            "doc_files",
            ["doc_file_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_sections_doc_file_id", ["doc_file_id"])

    with op.batch_alter_table("blocks") as batch:
        batch.add_column(sa.Column("page_width", sa.Float(), nullable=True))
        batch.add_column(sa.Column("page_height", sa.Float(), nullable=True))

    op.create_table(
        "references",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_references_document_id", "references", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_references_document_id", table_name="references")
    op.drop_table("references")
    with op.batch_alter_table("blocks") as batch:
        batch.drop_column("page_height")
        batch.drop_column("page_width")
    with op.batch_alter_table("sections") as batch:
        batch.drop_index("ix_sections_doc_file_id")
        batch.drop_constraint("fk_sections_doc_file_id", type_="foreignkey")
        batch.drop_column("doc_file_id")
    op.drop_index("ix_doc_files_document_id", table_name="doc_files")
    op.drop_table("doc_files")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("esi_hints_json")
        batch.drop_column("error_message")
        batch.drop_column("source_stem")
