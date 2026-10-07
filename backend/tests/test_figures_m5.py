"""Тесты M5: seed классов и порог уверенности классификатора."""

from __future__ import annotations

from pathlib import Path

from paper2data.core.project import create_project
from paper2data.db.models import FigureClass
from paper2data.db.session import dispose_db, session_scope
from paper2data.figures.classes import BUILTIN_FIGURE_CLASSES, seed_builtin_classes
from paper2data.figures.classifier import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    LabeledExample,
    classify_embedding,
    is_uncertain,
)
from paper2data.figures.embeddings import StubEmbeddingBackend, cosine_similarity
from sqlalchemy import select


def test_seed_builtin_classes_idempotent(tmp_path: Path):
    create_project(tmp_path / "proj", name="FigSeed")
    with session_scope() as session:
        rows = seed_builtin_classes(session)
        assert len(rows) >= len(BUILTIN_FIGURE_CLASSES)
        slugs = {c.slug for c in rows}
        for item in BUILTIN_FIGURE_CLASSES:
            assert item.slug in slugs
        count1 = len(session.scalars(select(FigureClass)).all())
        seed_builtin_classes(session)
        count2 = len(session.scalars(select(FigureClass)).all())
        assert count1 == count2
        builtins = [c for c in session.scalars(select(FigureClass)).all() if c.is_builtin]
        assert len(builtins) == len(BUILTIN_FIGURE_CLASSES)
    dispose_db()


def test_create_project_seeds_figure_classes(tmp_path: Path):
    create_project(tmp_path / "proj2", name="AutoSeed")
    with session_scope() as session:
        rows = session.scalars(select(FigureClass)).all()
        assert len(rows) == len(BUILTIN_FIGURE_CLASSES)
        assert all(c.is_builtin for c in rows)
    dispose_db()


def test_confidence_threshold_uncertain():
    assert is_uncertain(None) is True
    assert is_uncertain(0.0) is True
    assert is_uncertain(DEFAULT_CONFIDENCE_THRESHOLD - 0.01) is True
    assert is_uncertain(DEFAULT_CONFIDENCE_THRESHOLD) is False
    assert is_uncertain(0.99) is False


def test_knn_low_confidence_goes_uncertain():
    # ортогональные-ish векторы: низкая схожесть → uncertain
    ex = [
        LabeledExample(class_id=1, embedding=[1.0, 0.0, 0.0]),
        LabeledExample(class_id=1, embedding=[0.95, 0.05, 0.0]),
        LabeledExample(class_id=2, embedding=[0.0, 1.0, 0.0]),
    ]
    # почти ортогонален к обоим
    query = [0.0, 0.0, 1.0]
    result = classify_embedding(query, ex, threshold=0.55, k=3)
    assert result.class_id in (1, 2)
    assert result.confidence < 0.55
    assert result.uncertain is True
    assert result.method == "knn"


def test_knn_high_confidence_assigns_class():
    ex = [
        LabeledExample(class_id=7, embedding=[1.0, 0.0, 0.0]),
        LabeledExample(class_id=7, embedding=[0.99, 0.01, 0.0]),
        LabeledExample(class_id=3, embedding=[0.0, 1.0, 0.0]),
    ]
    query = [0.98, 0.02, 0.0]
    result = classify_embedding(query, ex, threshold=0.55, k=2)
    assert result.class_id == 7
    assert result.confidence >= 0.55
    assert result.uncertain is False


def test_empty_examples_uncertain():
    result = classify_embedding([1.0, 0.0], [], threshold=0.55)
    assert result.class_id is None
    assert result.uncertain is True
    assert result.method == "empty"


def test_stub_embedding_deterministic(tmp_path: Path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    backend = StubEmbeddingBackend()
    v1 = backend.embed_image(img)
    v2 = backend.embed_image(img)
    assert len(v1) == backend.dim
    assert v1 == v2
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-6
