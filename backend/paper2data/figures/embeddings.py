"""Плагable бэкенд эмбеддингов для классификации рисунков.

По умолчанию — лёгкий stub (детерминированный вектор из байтов изображения),
чтобы UI/API работали без тяжёлых зависимостей на Windows.

Опционально (если установлены):
- open_clip + torch
- sentence-transformers (CLIP-модель)

См. README: раздел «Рисунки (M5) / CLIP».
"""

from __future__ import annotations

import hashlib
import math
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence


DEFAULT_DIM = 512


class EmbeddingBackend(ABC):
    """Интерфейс эмбеддинга изображения."""

    name: str = "abstract"
    dim: int = DEFAULT_DIM

    @abstractmethod
    def embed_image(self, path: Path) -> list[float]:
        raise NotImplementedError


class StubEmbeddingBackend(EmbeddingBackend):
    """Детерминированный псевдо-эмбеддинг без внешних ML-зависимостей."""

    name = "stub"
    dim = DEFAULT_DIM

    def embed_image(self, path: Path) -> list[float]:
        data = path.read_bytes()
        return _hash_to_unit_vector(data, self.dim)


def _hash_to_unit_vector(data: bytes, dim: int) -> list[float]:
    seed = hashlib.sha256(data).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + struct.pack(">I", counter)).digest()
        for i in range(0, len(block) - 3, 4):
            raw = struct.unpack(">I", block[i : i + 4])[0]
            # [-1, 1]
            values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(values) >= dim:
                break
        counter += 1
    return _l2_normalize(values)


def _l2_normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
    return [float(x) / norm for x in vec]


class OpenClipEmbeddingBackend(EmbeddingBackend):
    """open_clip ViT-B-32 (ленивая загрузка)."""

    name = "open_clip"
    dim = 512

    def __init__(self) -> None:
        import open_clip  # type: ignore
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        self._torch = torch
        self._Image = Image
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai"
        )
        model.eval()
        self._model = model
        self._preprocess = preprocess

    def embed_image(self, path: Path) -> list[float]:
        image = self._preprocess(self._Image.open(path).convert("RGB")).unsqueeze(0)
        with self._torch.no_grad():
            feats = self._model.encode_image(image)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return [float(x) for x in feats[0].tolist()]


class SentenceTransformersClipBackend(EmbeddingBackend):
    """sentence-transformers CLIP (clip-ViT-B-32)."""

    name = "sentence_transformers_clip"
    dim = 512

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer("clip-ViT-B-32")

    def embed_image(self, path: Path) -> list[float]:
        vec = self._model.encode([str(path)], convert_to_numpy=True)[0]
        return _l2_normalize([float(x) for x in vec.tolist()])


_cached_backend: EmbeddingBackend | None = None
_backend_error: str | None = None


def get_embedding_backend(*, prefer: str | None = None, force_reload: bool = False) -> EmbeddingBackend:
    """Выбрать доступный бэкенд: open_clip → sentence-transformers → stub."""
    global _cached_backend, _backend_error
    if _cached_backend is not None and not force_reload:
        return _cached_backend

    errors: list[str] = []
    order = ["open_clip", "sentence_transformers_clip", "stub"]
    if prefer:
        order = [prefer] + [x for x in order if x != prefer]

    for name in order:
        try:
            if name == "open_clip":
                backend: EmbeddingBackend = OpenClipEmbeddingBackend()
            elif name == "sentence_transformers_clip":
                backend = SentenceTransformersClipBackend()
            else:
                backend = StubEmbeddingBackend()
            _cached_backend = backend
            _backend_error = None if name != "stub" else (
                "CLIP не установлен — используется stub-эмбеддинг. "
                "Опционально: pip install open-clip-torch pillow  "
                "или sentence-transformers"
            )
            return backend
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue

    backend = StubEmbeddingBackend()
    _cached_backend = backend
    _backend_error = "; ".join(errors) or "fallback stub"
    return backend


def embedding_status() -> dict[str, str | bool | int]:
    backend = get_embedding_backend()
    return {
        "backend": backend.name,
        "dim": backend.dim,
        "is_stub": backend.name == "stub",
        "note": _backend_error or "",
    }


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(float(x) * float(y) for x, y in zip(a, b)))
