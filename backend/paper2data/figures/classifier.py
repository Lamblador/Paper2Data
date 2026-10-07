"""Классификатор рисунков: прототипы / kNN по эмбеддингам, порог уверенности."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from paper2data.figures.embeddings import cosine_similarity

# Ниже порога → корзина «Не уверен»
DEFAULT_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_K = 5


@dataclass(frozen=True)
class LabeledExample:
    class_id: int
    embedding: list[float]


@dataclass(frozen=True)
class ClassificationResult:
    class_id: int | None
    confidence: float
    uncertain: bool
    neighbors: int
    method: str  # prototype | knn | empty


def classify_embedding(
    embedding: Sequence[float],
    examples: Sequence[LabeledExample],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    k: int = DEFAULT_K,
) -> ClassificationResult:
    """
    Классификация on-the-fly:
    1) если есть размеченные примеры — kNN по cosine;
    2) иначе — uncertain (нет обучающих данных).

    Уверенность = средняя cosine среди k ближайших того же класса-победителя.
    При confidence < threshold → uncertain=True, class_id всё же предлагается.
    """
    if not examples:
        return ClassificationResult(
            class_id=None,
            confidence=0.0,
            uncertain=True,
            neighbors=0,
            method="empty",
        )

    scored: list[tuple[float, int]] = []
    for ex in examples:
        sim = cosine_similarity(embedding, ex.embedding)
        scored.append((sim, ex.class_id))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[: max(1, k)]

    votes: dict[int, list[float]] = defaultdict(list)
    for sim, cid in top:
        votes[cid].append(sim)

    # Победитель: наибольшая средняя similarity среди голосов в top-k
    best_cid = max(votes.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[0]
    conf = sum(votes[best_cid]) / len(votes[best_cid])
    uncertain = conf < threshold
    return ClassificationResult(
        class_id=best_cid,
        confidence=float(conf),
        uncertain=uncertain,
        neighbors=len(top),
        method="knn",
    )


def build_prototypes(examples: Sequence[LabeledExample]) -> dict[int, list[float]]:
    """Средний вектор (прототип) по каждому классу."""
    buckets: dict[int, list[list[float]]] = defaultdict(list)
    for ex in examples:
        buckets[ex.class_id].append(list(ex.embedding))
    prototypes: dict[int, list[float]] = {}
    for cid, vecs in buckets.items():
        dim = len(vecs[0])
        avg = [0.0] * dim
        for v in vecs:
            for i, x in enumerate(v):
                avg[i] += float(x)
        n = float(len(vecs))
        prototypes[cid] = [x / n for x in avg]
    return prototypes


def classify_by_prototypes(
    embedding: Sequence[float],
    prototypes: dict[int, list[float]],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ClassificationResult:
    if not prototypes:
        return ClassificationResult(
            class_id=None,
            confidence=0.0,
            uncertain=True,
            neighbors=0,
            method="empty",
        )
    best_cid = None
    best_sim = -1.0
    for cid, proto in prototypes.items():
        sim = cosine_similarity(embedding, proto)
        if sim > best_sim:
            best_sim = sim
            best_cid = cid
    return ClassificationResult(
        class_id=best_cid,
        confidence=float(best_sim),
        uncertain=best_sim < threshold,
        neighbors=len(prototypes),
        method="prototype",
    )


def is_uncertain(confidence: float | None, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
    if confidence is None:
        return True
    return float(confidence) < threshold
