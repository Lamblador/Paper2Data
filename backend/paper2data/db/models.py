"""Модели SQLAlchemy: M0–M5 + корпус/оценка (M4).

M1 наполняет Document / DocFile / Section / Block / Reference.
M2 использует Block.id в Evidence и Document для графа.
M3: Recipe / ExtractionRun.
M4: Evaluation, расширенный Job (пакетные прогоны).
M5: Figure / FigureClass (галерея и классификация).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    """Служебные ключ-значение для версии схемы БД и метаданных проекта."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Job(Base):
    """Фоновые задачи: пакетные прогоны, оценка (M4)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    # pending | queued | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


SECTION_USEFUL_DEFAULT: dict[str, bool] = {
    "abstract": True,
    "introduction": False,
    "experimental": True,
    "results": True,
    "conclusion": True,
    "acknowledgments": False,
    "references": False,
    "esi": True,
    "other": True,
}


# ---------------------------------------------------------------------------
# Ingest (M1)
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    doi: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # indexed | parsing | parsed | error | new | annotated | gold | extracted
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="indexed")
    source_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    source_stem: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    esi_hints_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    files: Mapped[list[DocFile]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    sections: Mapped[list[Section]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    blocks: Mapped[list[Block]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    references: Mapped[list[Reference]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    nodes: Mapped[list[Node]] = relationship(back_populates="document")
    edges: Mapped[list[Edge]] = relationship(back_populates="document")
    gold_snapshots: Mapped[list[GoldSnapshot]] = relationship(back_populates="document")
    figures: Mapped[list[Figure]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocFile(Base):
    __tablename__ = "doc_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="main")
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="files")
    sections: Mapped[list[Section]] = relationship(back_populates="doc_file")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("doc_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    section_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    page_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    useful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped[Document] = relationship(back_populates="sections")
    doc_file: Mapped[Optional[DocFile]] = relationship(back_populates="sections")
    blocks: Mapped[list[Block]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # paragraph | table_cell | table | caption | other
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="paragraph")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # [x0,y0,x1,y1]
    page_width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    page_height: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    document: Mapped[Document] = relationship(back_populates="blocks")
    section: Mapped[Optional[Section]] = relationship(back_populates="blocks")
    evidences: Mapped[list[Evidence]] = relationship(back_populates="block")


class Reference(Base):
    __tablename__ = "references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doi: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped[Document] = relationship(back_populates="references")


# ---------------------------------------------------------------------------
# Schema (онтология проекта) — M2
# ---------------------------------------------------------------------------


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    template_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    yaml_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entity_types: Mapped[list[EntityType]] = relationship(back_populates="schema_version")
    relation_types: Mapped[list[RelationType]] = relationship(
        back_populates="schema_version"
    )


class EntityType(Base):
    __tablename__ = "entity_types"
    __table_args__ = (
        UniqueConstraint("schema_version_id", "type_id", name="uq_entity_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version_id: Mapped[int] = mapped_column(
        ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    label_attribute: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    schema_version: Mapped[SchemaVersion] = relationship(back_populates="entity_types")
    attributes: Mapped[list[AttributeDef]] = relationship(
        back_populates="entity_type", cascade="all, delete-orphan"
    )
    nodes: Mapped[list[Node]] = relationship(back_populates="entity_type")


class AttributeDef(Base):
    __tablename__ = "attribute_defs"
    __table_args__ = (
        UniqueConstraint("entity_type_id", "attr_id", name="uq_attr_def"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type_id: Mapped[int] = mapped_column(
        ForeignKey("entity_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attr_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    attr_type: Mapped[str] = mapped_column(String(64), nullable=False, default="text")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    enum_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    llm_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    entity_type: Mapped[EntityType] = relationship(back_populates="attributes")


class RelationType(Base):
    __tablename__ = "relation_types"
    __table_args__ = (
        UniqueConstraint("schema_version_id", "type_id", name="uq_relation_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version_id: Mapped[int] = mapped_column(
        ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    from_type: Mapped[str] = mapped_column(String(128), nullable=False)
    to_type: Mapped[str] = mapped_column(String(128), nullable=False)
    cardinality: Mapped[str] = mapped_column(String(32), nullable=False, default="N:N")
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    llm_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    schema_version: Mapped[SchemaVersion] = relationship(back_populates="relation_types")
    edges: Mapped[list[Edge]] = relationship(back_populates="relation_type")


# ---------------------------------------------------------------------------
# Graph instances — M2
# ---------------------------------------------------------------------------


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type_id: Mapped[int] = mapped_column(
        ForeignKey("entity_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    canonical_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    document: Mapped[Document] = relationship(back_populates="nodes")
    entity_type: Mapped[EntityType] = relationship(back_populates="nodes")
    evidences: Mapped[list[Evidence]] = relationship(
        back_populates="node",
        foreign_keys="Evidence.node_id",
        cascade="all, delete-orphan",
    )


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type_id: Mapped[int] = mapped_column(
        ForeignKey("relation_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    document: Mapped[Document] = relationship(back_populates="edges")
    relation_type: Mapped[RelationType] = relationship(back_populates="edges")
    evidences: Mapped[list[Evidence]] = relationship(
        back_populates="edge",
        foreign_keys="Evidence.edge_id",
        cascade="all, delete-orphan",
    )


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="node")
    node_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    edge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("edges.id", ondelete="CASCADE"), nullable=True, index=True
    )
    attribute_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    block_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    char_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Optional[Node]] = relationship(
        back_populates="evidences", foreign_keys=[node_id]
    )
    edge: Mapped[Optional[Edge]] = relationship(
        back_populates="evidences", foreign_keys=[edge_id]
    )
    block: Mapped[Optional[Block]] = relationship(back_populates="evidences")


class GoldSnapshot(Base):
    __tablename__ = "gold_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(256), nullable=False, default="gold")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="gold_snapshots")


# ---------------------------------------------------------------------------
# Figures (M5)
# ---------------------------------------------------------------------------


class FigureClass(Base):
    """Класс рисунка: базовые (seed) + пользовательские."""

    __tablename__ = "figure_classes"
    __table_args__ = (UniqueConstraint("slug", name="uq_figure_class_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    figures: Mapped[list[Figure]] = relationship(back_populates="figure_class")


class Figure(Base):
    """Извлечённый рисунок: страница, подпись, путь в cache/, bbox, класс."""

    __tablename__ = "figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # путь относительно cache/ проекта, напр. figures/12/emb_p1_0.png
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    bbox_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # [x0,y0,x1,y1]
    # embedded | caption_region
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="embedded")
    class_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("figure_classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    manual_label: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="figures")
    figure_class: Mapped[Optional[FigureClass]] = relationship(back_populates="figures")


# ---------------------------------------------------------------------------
# Extraction (M3)
# ---------------------------------------------------------------------------


class Recipe(Base):
    """Версия рецепта извлечения (YAML snapshot в проекте / БД)."""

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    schema_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    yaml_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    runs: Mapped[list[ExtractionRun]] = relationship(back_populates="recipe")


class ExtractionRun(Base):
    """Один прогон извлечения по документу."""

    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipe_db_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    llm_profile_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="entities_first")
    # pending | running | awaiting_review | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    current_step_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    abbreviation_map_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    document: Mapped[Document] = relationship()
    recipe: Mapped[Optional[Recipe]] = relationship(back_populates="runs")
    evaluations: Mapped[list[Evaluation]] = relationship(back_populates="extraction_run")


class Evaluation(Base):
    """Метрики прогона vs эталон (GoldSnapshot)."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gold_snapshot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("gold_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    attribute_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edge_f1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verified_quote_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="evaluations")
    gold_snapshot: Mapped[Optional[GoldSnapshot]] = relationship()
    document: Mapped[Document] = relationship()


class AssistantThread(Base):
    """История чата ассистента для одной статьи."""

    __tablename__ = "assistant_threads"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_assistant_thread_document"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    messages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    events_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    pending_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    document: Mapped[Document] = relationship()
