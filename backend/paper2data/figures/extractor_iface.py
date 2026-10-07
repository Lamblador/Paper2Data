"""Заготовка интерфейса извлечения данных из рисунков (OCSR, дигитайзер графиков)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FigureDataResult:
    """Результат будущего извлечения содержимого рисунка."""

    kind: str  # ocsr | graph_digitize | table_ocr | unknown
    success: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class FigureDataExtractor(ABC):
    """
    Интерфейс для будущих экстракторов (M6+ / будущее):
    - OCSR структурных формул
    - дигитайзер спектров / кривых
    - OCR таблиц из изображений
    """

    name: str = "abstract"

    @abstractmethod
    def supports(self, figure_class_slug: str | None) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, image_path: Path, *, meta: dict[str, Any] | None = None) -> FigureDataResult:
        raise NotImplementedError


class StubFigureDataExtractor(FigureDataExtractor):
    """Заглушка: всегда сообщает, что извлечение ещё не реализовано."""

    name = "stub"

    def supports(self, figure_class_slug: str | None) -> bool:
        return True

    def extract(self, image_path: Path, *, meta: dict[str, Any] | None = None) -> FigureDataResult:
        return FigureDataResult(
            kind="unknown",
            success=False,
            payload={"path": str(image_path), "meta": meta or {}},
            message="Извлечение данных из рисунков пока не реализовано (заглушка FigureDataExtractor).",
        )


def get_default_extractor() -> FigureDataExtractor:
    return StubFigureDataExtractor()
