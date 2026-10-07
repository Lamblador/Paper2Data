"""Подсчёт токенов и оценка стоимости пакетного прогона."""

from __future__ import annotations

from typing import Any

# Средний выход на шаг рецепта, если нет истории эталонных прогонов
DEFAULT_OUTPUT_TOKENS_PER_STEP = 800
DEFAULT_CHARS_PER_TOKEN = 4.0


def count_tokens(text: str, *, encoding_name: str = "cl100k_base") -> int:
    """tiktoken при наличии, иначе эвристика chars/4."""
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001 — fallback без зависимости
        return max(1, int(len(text) / DEFAULT_CHARS_PER_TOKEN))


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += count_tokens(str(msg.get("content") or ""))
        # небольшой оверхед роли
        total += 4
    return total


def cost_usd(
    tokens_in: int,
    tokens_out: int,
    *,
    price_in_per_1m: float,
    price_out_per_1m: float,
) -> float:
    """Стоимость в USD по ценам профиля за 1M токенов."""
    return (tokens_in * price_in_per_1m + tokens_out * price_out_per_1m) / 1_000_000.0


def average_output_tokens_from_runs(stats_list: list[dict[str, Any]]) -> float | None:
    """Среднее completion_tokens из stats прошлых прогонов."""
    vals: list[float] = []
    for st in stats_list:
        if not st:
            continue
        out = st.get("completion_tokens")
        if out is None:
            out = st.get("tokens_out")
        if out is None and isinstance(st.get("tokens"), dict):
            out = st["tokens"].get("completion_tokens")
        if out is not None:
            try:
                vals.append(float(out))
            except (TypeError, ValueError):
                continue
    if not vals:
        return None
    return sum(vals) / len(vals)


def estimate_batch_cost(
    *,
    document_ids: list[int],
    profiles: list[dict[str, Any]],
    steps_per_document: int,
    prompt_tokens_by_doc: dict[int, int],
    avg_output_tokens_per_run: float | None = None,
    default_output_per_step: int = DEFAULT_OUTPUT_TOKENS_PER_STEP,
) -> dict[str, Any]:
    """Оценка токенов/стоимости: docs × profiles.

    prompt_tokens_by_doc — сумма токенов промптов+чанков по всем шагам рецепта.
    output — avg из эталонных прогонов или default_output_per_step * steps.
    """
    out_per_doc = (
        float(avg_output_tokens_per_run)
        if avg_output_tokens_per_run is not None
        else float(default_output_per_step * max(1, steps_per_document))
    )
    tokenizer = "tiktoken"
    try:
        import tiktoken  # noqa: F401
    except ImportError:
        tokenizer = "heuristic"

    by_model: list[dict[str, Any]] = []
    grand_in = 0
    grand_out = 0
    grand_cost = 0.0

    for profile in profiles:
        pid = profile.get("id") or profile.get("profile_id")
        price_in = float(profile.get("price_in_per_1m") or 0.0)
        price_out = float(profile.get("price_out_per_1m") or 0.0)
        tokens_in = 0
        for doc_id in document_ids:
            tokens_in += int(prompt_tokens_by_doc.get(doc_id, 0))
        tokens_out = int(round(out_per_doc * len(document_ids)))
        c = cost_usd(
            tokens_in,
            tokens_out,
            price_in_per_1m=price_in,
            price_out_per_1m=price_out,
        )
        by_model.append(
            {
                "llm_profile_id": pid,
                "name": profile.get("name") or pid,
                "model": profile.get("model"),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "price_in_per_1m": price_in,
                "price_out_per_1m": price_out,
                "cost_usd": round(c, 6),
                "documents": len(document_ids),
            }
        )
        grand_in += tokens_in
        grand_out += tokens_out
        grand_cost += c

    return {
        "tokenizer": tokenizer,
        "steps_per_document": steps_per_document,
        "avg_output_tokens_per_document": out_per_doc,
        "output_source": (
            "gold_run_average" if avg_output_tokens_per_run is not None else "heuristic_default"
        ),
        "by_model": by_model,
        "totals": {
            "tokens_in": grand_in,
            "tokens_out": grand_out,
            "cost_usd": round(grand_cost, 6),
            "combinations": len(document_ids) * len(profiles),
        },
        "prompt_tokens_by_doc": {str(k): v for k, v in prompt_tokens_by_doc.items()},
    }


def estimate_prompt_tokens_for_document(texts: list[str]) -> int:
    """Сумма токенов по списку текстов промптов (шаги рецепта)."""
    return sum(count_tokens(t) for t in texts)
