"""M2: schema + graph + document/block stubs for evidence.

Revision ID: 0002_m2_schema_graph
Revises: 0001_m0_initial
Create Date: 2026-03-28 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_m2_schema_graph"
down_revision: Union[str, None] = "0001_m0_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "sections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_sections_document_id", "sections", ["document_id"])

    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_blocks_document_id", "blocks", ["document_id"])
    op.create_index("ix_blocks_section_id", "blocks", ["section_id"])

    op.create_table(
        "schema_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("yaml_snapshot", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "entity_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schema_version_id", sa.Integer(), sa.ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("label_attribute", sa.String(length=128), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("schema_version_id", "type_id", name="uq_entity_type"),
    )
    op.create_index("ix_entity_types_schema_version_id", "entity_types", ["schema_version_id"])

    op.create_table(
        "attribute_defs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type_id", sa.Integer(), sa.ForeignKey("entity_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attr_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("attr_type", sa.String(length=64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("enum_values_json", sa.Text(), nullable=False),
        sa.Column("llm_hint", sa.Text(), nullable=False),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("entity_type_id", "attr_id", name="uq_attr_def"),
    )
    op.create_index("ix_attribute_defs_entity_type_id", "attribute_defs", ["entity_type_id"])

    op.create_table(
        "relation_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schema_version_id", sa.Integer(), sa.ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("from_type", sa.String(length=128), nullable=False),
        sa.Column("to_type", sa.String(length=128), nullable=False),
        sa.Column("cardinality", sa.String(length=32), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("llm_hint", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("schema_version_id", "type_id", name="uq_relation_type"),
    )
    op.create_index("ix_relation_types_schema_version_id", "relation_types", ["schema_version_id"])

    op.create_table(
        "nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type_id", sa.Integer(), sa.ForeignKey("entity_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("canonical_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("pos_x", sa.Float(), nullable=False),
        sa.Column("pos_y", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_nodes_document_id", "nodes", ["document_id"])
    op.create_index("ix_nodes_entity_type_id", "nodes", ["entity_type_id"])

    op.create_table(
        "edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type_id", sa.Integer(), sa.ForeignKey("relation_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_edges_document_id", "edges", ["document_id"])
    op.create_index("ix_edges_relation_type_id", "edges", ["relation_type_id"])
    op.create_index("ix_edges_source_node_id", "edges", ["source_node_id"])
    op.create_index("ix_edges_target_node_id", "edges", ["target_node_id"])

    op.create_table(
        "evidences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("edge_id", sa.Integer(), sa.ForeignKey("edges.id", ondelete="CASCADE"), nullable=True),
        sa.Column("attribute_key", sa.String(length=128), nullable=True),
        sa.Column("block_id", sa.Integer(), sa.ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_evidences_node_id", "evidences", ["node_id"])
    op.create_index("ix_evidences_edge_id", "evidences", ["edge_id"])
    op.create_index("ix_evidences_block_id", "evidences", ["block_id"])

    op.create_table(
        "gold_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gold_snapshots_document_id", "gold_snapshots", ["document_id"])


def downgrade() -> None:
    op.drop_table("gold_snapshots")
    op.drop_table("evidences")
    op.drop_table("edges")
    op.drop_table("nodes")
    op.drop_table("relation_types")
    op.drop_table("attribute_defs")
    op.drop_table("entity_types")
    op.drop_table("schema_versions")
    op.drop_table("blocks")
    op.drop_table("sections")
    op.drop_table("documents")
