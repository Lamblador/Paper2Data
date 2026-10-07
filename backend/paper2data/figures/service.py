"""Сервис рисунков: seed классов, извлечение, разметка, автоклассификация."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from paper2data.core.project import ProjectState
from paper2data.db.models import Document, Figure, FigureClass
from paper2data.figures.classes import create_user_class, seed_builtin_classes
from paper2data.figures.classifier import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    LabeledExample,
    ClassificationResult,
    classify_embedding,
    is_uncertain,
)
from paper2data.figures.embeddings import (
    embedding_status,
    get_embedding_backend,
)
from paper2data.figures.extract import dumps_bbox, extract_figures_from_pdf
from paper2data.figures.extractor_iface import get_default_extractor


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _abs_from_rel(project: ProjectState, relative_path: str) -> Path:
    papers = project.papers_dir.resolve()
    path = (project.papers_dir / relative_path).resolve()
    path.relative_to(papers)
    return path


def ensure_classes_seeded(session: Session) -> list[FigureClass]:
    return seed_builtin_classes(session)


def serialize_class(row: FigureClass) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "description": row.description,
        "is_builtin": row.is_builtin,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_figure(fig: Figure, *, include_embedding: bool = False) -> dict[str, Any]:
    cls = fig.figure_class
    data: dict[str, Any] = {
        "id": fig.id,
        "document_id": fig.document_id,
        "page": fig.page,
        "caption": fig.caption,
        "image_path": fig.image_path,
        "bbox": _loads(fig.bbox_json, None),
        "source_kind": fig.source_kind,
        "class_id": fig.class_id,
        "class_slug": cls.slug if cls else None,
        "class_name": cls.name if cls else None,
        "confidence": fig.confidence,
        "manual_label": fig.manual_label,
        "uncertain": fig.uncertain,
        "order_index": fig.order_index,
        "meta": _loads(fig.meta_json, {}),
        "created_at": fig.created_at.isoformat() if fig.created_at else None,
        "image_url": f"/api/figures/{fig.id}/image",
    }
    if include_embedding:
        data["embedding"] = _loads(fig.embedding_json, None)
    return data


def list_classes(session: Session) -> list[dict[str, Any]]:
    ensure_classes_seeded(session)
    rows = session.scalars(select(FigureClass).order_by(FigureClass.is_builtin.desc(), FigureClass.id)).all()
    return [serialize_class(c) for c in rows]


def add_class(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    ensure_classes_seeded(session)
    row = create_user_class(session, slug=slug, name=name, description=description)
    return serialize_class(row)


def clear_document_figures(session: Session, project: ProjectState, document_id: int) -> None:
    figs = session.scalars(select(Figure).where(Figure.document_id == document_id)).all()
    for fig in figs:
        session.delete(fig)
    session.flush()
    fig_dir = project.cache_dir / "figures" / str(document_id)
    if fig_dir.exists():
        shutil.rmtree(fig_dir, ignore_errors=True)


def extract_and_store_figures(
    session: Session,
    project: ProjectState,
    document_id: int,
    *,
    replace: bool = True,
    auto_classify: bool = True,
) -> list[dict[str, Any]]:
    """Извлечь рисунки из main PDF документа и сохранить Figure-записи."""
    ensure_classes_seeded(session)
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.files), selectinload(Document.blocks))
    )
    if document is None:
        raise KeyError(f"Документ {document_id} не найден")

    main = next((f for f in document.files if f.role == "main"), None)
    if main is None:
        raise FileNotFoundError("Нет основного PDF (role=main)")
    pdf_path = _abs_from_rel(project, main.relative_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {main.relative_path}")

    if replace:
        clear_document_figures(session, project, document_id)

    caption_blocks = [
        {
            "page": b.page,
            "text": b.text,
            "bbox": _loads(b.bbox_json, None),
        }
        for b in document.blocks
        if b.kind == "caption" and b.page
    ]

    extracted = extract_figures_from_pdf(
        pdf_path,
        project.cache_dir,
        document_id,
        caption_blocks=caption_blocks,
    )

    backend = get_embedding_backend()
    rows: list[Figure] = []
    for item in extracted:
        abs_img = project.cache_dir / item.image_path
        embedding = None
        if abs_img.is_file():
            try:
                embedding = backend.embed_image(abs_img)
            except Exception:  # noqa: BLE001
                embedding = None
        fig = Figure(
            document_id=document_id,
            page=item.page,
            caption=item.caption,
            image_path=item.image_path,
            bbox_json=dumps_bbox(item.bbox),
            source_kind=item.source_kind,
            order_index=item.order_index,
            meta_json=_dumps(item.meta),
            embedding_json=_dumps(embedding) if embedding else None,
        )
        session.add(fig)
        rows.append(fig)
    session.flush()

    if auto_classify:
        _classify_figures(session, rows)

    session.flush()
    return [
        serialize_figure(f)
        for f in session.scalars(
            select(Figure)
            .where(Figure.document_id == document_id)
            .options(selectinload(Figure.figure_class))
            .order_by(Figure.order_index)
        ).all()
    ]


def _labeled_examples(session: Session) -> list[LabeledExample]:
    """Примеры только с ручной меткой и сохранённым эмбеддингом."""
    rows = session.scalars(
        select(Figure).where(
            Figure.manual_label.is_(True),
            Figure.class_id.is_not(None),
            Figure.embedding_json.is_not(None),
        )
    ).all()
    examples: list[LabeledExample] = []
    for fig in rows:
        emb = _loads(fig.embedding_json, None)
        if isinstance(emb, list) and fig.class_id is not None:
            examples.append(LabeledExample(class_id=fig.class_id, embedding=[float(x) for x in emb]))
    return examples


def _classify_figures(session: Session, figures: list[Figure]) -> None:
    examples = _labeled_examples(session)
    for fig in figures:
        if fig.manual_label:
            continue
        emb = _loads(fig.embedding_json, None)
        if not isinstance(emb, list):
            fig.uncertain = True
            fig.confidence = 0.0
            fig.class_id = None
            continue
        result = classify_embedding(
            [float(x) for x in emb],
            examples,
            threshold=DEFAULT_CONFIDENCE_THRESHOLD,
        )
        _apply_result(fig, result)


def _apply_result(fig: Figure, result: ClassificationResult) -> None:
    fig.class_id = result.class_id
    fig.confidence = result.confidence
    fig.uncertain = result.uncertain or result.class_id is None


def list_figures(
    session: Session,
    *,
    document_id: int | None = None,
    uncertain_only: bool = False,
    class_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_classes_seeded(session)
    stmt = select(Figure).options(selectinload(Figure.figure_class)).order_by(
        Figure.document_id, Figure.order_index, Figure.id
    )
    if document_id is not None:
        stmt = stmt.where(Figure.document_id == document_id)
    if uncertain_only:
        stmt = stmt.where(Figure.uncertain.is_(True))
    if class_id is not None:
        stmt = stmt.where(Figure.class_id == class_id)
    return [serialize_figure(f) for f in session.scalars(stmt).all()]


def get_figure(session: Session, figure_id: int) -> Figure:
    fig = session.scalar(
        select(Figure)
        .where(Figure.id == figure_id)
        .options(selectinload(Figure.figure_class))
    )
    if fig is None:
        raise KeyError(f"Рисунок {figure_id} не найден")
    return fig


def assign_class(
    session: Session,
    figure_id: int,
    class_id: int | None,
    *,
    manual: bool = True,
) -> dict[str, Any]:
    ensure_classes_seeded(session)
    fig = get_figure(session, figure_id)
    if class_id is not None:
        cls = session.get(FigureClass, class_id)
        if cls is None:
            raise KeyError(f"Класс {class_id} не найден")
    fig.class_id = class_id
    fig.manual_label = manual and class_id is not None
    if fig.manual_label:
        fig.uncertain = False
        fig.confidence = 1.0
    elif class_id is None:
        fig.uncertain = True
        fig.confidence = 0.0
        fig.manual_label = False
    session.flush()
    return serialize_figure(fig)


def classify_figure(session: Session, figure_id: int) -> dict[str, Any]:
    fig = get_figure(session, figure_id)
    if fig.manual_label:
        return serialize_figure(fig)
    emb = _loads(fig.embedding_json, None)
    if not isinstance(emb, list):
        # пересчитать эмбеддинг нельзя без project path — uncertain
        fig.uncertain = True
        fig.confidence = 0.0
        session.flush()
        return serialize_figure(fig)
    result = classify_embedding(
        [float(x) for x in emb],
        _labeled_examples(session),
        threshold=DEFAULT_CONFIDENCE_THRESHOLD,
    )
    _apply_result(fig, result)
    session.flush()
    return serialize_figure(fig)


def classify_all(
    session: Session,
    *,
    document_id: int | None = None,
    only_unlabeled: bool = True,
) -> dict[str, Any]:
    stmt = select(Figure)
    if document_id is not None:
        stmt = stmt.where(Figure.document_id == document_id)
    if only_unlabeled:
        stmt = stmt.where(Figure.manual_label.is_(False))
    figs = list(session.scalars(stmt).all())
    _classify_figures(session, figs)
    session.flush()
    return {
        "classified": len(figs),
        "uncertain": sum(1 for f in figs if f.uncertain),
        "embedding": embedding_status(),
        "threshold": DEFAULT_CONFIDENCE_THRESHOLD,
    }


def resolve_figure_image_path(project: ProjectState, fig: Figure) -> Path:
    path = (project.cache_dir / fig.image_path).resolve()
    path.relative_to(project.cache_dir.resolve())
    if not path.is_file():
        raise FileNotFoundError(fig.image_path)
    return path


def try_extract_data(session: Session, project: ProjectState, figure_id: int) -> dict[str, Any]:
    """Вызов заглушки FigureDataExtractor."""
    fig = get_figure(session, figure_id)
    path = resolve_figure_image_path(project, fig)
    extractor = get_default_extractor()
    slug = fig.figure_class.slug if fig.figure_class else None
    result = extractor.extract(path, meta={"figure_id": fig.id, "class_slug": slug})
    return {
        "extractor": extractor.name,
        "supports": extractor.supports(slug),
        "kind": result.kind,
        "success": result.success,
        "message": result.message,
        "payload": result.payload,
    }


def confidence_threshold() -> float:
    return DEFAULT_CONFIDENCE_THRESHOLD


def check_uncertain(confidence: float | None, threshold: float | None = None) -> bool:
    return is_uncertain(confidence, threshold if threshold is not None else DEFAULT_CONFIDENCE_THRESHOLD)
