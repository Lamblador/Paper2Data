"""Рисунки: извлечение, классы, CLIP+kNN классификация (M5).

Детекция DocLayout/YOLO намеренно не используется — см. extract.py и README.
Эмбеддинги: open_clip / sentence-transformers при наличии, иначе stub.
"""

from paper2data.figures.classes import BUILTIN_FIGURE_CLASSES, seed_builtin_classes
from paper2data.figures.classifier import DEFAULT_CONFIDENCE_THRESHOLD
from paper2data.figures.embeddings import embedding_status, get_embedding_backend
from paper2data.figures.extractor_iface import FigureDataExtractor, StubFigureDataExtractor

__all__ = [
    "BUILTIN_FIGURE_CLASSES",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "FigureDataExtractor",
    "StubFigureDataExtractor",
    "embedding_status",
    "get_embedding_backend",
    "seed_builtin_classes",
]
