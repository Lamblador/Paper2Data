"""OpenAI-совместимый клиент (httpx) для проверки подключения и чата."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from paper2data.core.project import LlmProfileConfig
from paper2data.llm import secrets as secrets_store


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _resolve_key(profile: LlmProfileConfig, api_key: str | None = None) -> str:
    key = api_key if api_key is not None else secrets_store.get_secret(profile.secret_ref)
    if not key:
        key = "EMPTY"
    return key


# Закрытый блок: Qwen продолжает ответ уже после reasoning.
_THINK_PREFILL = "<think>\n\n</think>\n\n"


def is_local_base_url(base_url: str) -> bool:
    """True для localhost, LAN/private IP и CGNAT (Tailscale 100.64/10)."""
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    try:
        import ipaddress

        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            return True
        # RFC 6598 shared address space (Tailscale и т.п.)
        if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network(
            "100.64.0.0/10"
        ):
            return True
    except ValueError:
        # hostname вроде "lmstudio.local" — считаем локальным сервисом
        if host.endswith(".local") or host.endswith(".lan"):
            return True
    return False


def is_deepseek_base_url(base_url: str) -> bool:
    """True для api.deepseek.com (и зеркал с deepseek в хосте)."""
    host = (urlparse(base_url).hostname or "").lower()
    return "deepseek.com" in host


def _timeout_message(timeout: float) -> str:
    return (
        f"Модель не ответила за {int(timeout)} с, запрос прерван. "
        "Локальные модели на больших шагах (OLED-стек: десятки Layer) "
        "часто не укладываются в короткий лимит. "
        "Выключите Thinking в LM Studio; для стека — одно Device за ответ. "
        "Словарь обозначений, если он уже пришёл с предыдущего фрагмента, сохранён в прогоне."
    )


def default_chat_timeout(profile: LlmProfileConfig) -> float:
    """Локальные LLM — дольше; DeepSeek на длинных стеках — 300 с; прочее облако — 180 с."""
    if is_local_base_url(profile.base_url):
        return 600.0
    if is_deepseek_base_url(profile.base_url):
        return 300.0
    return 180.0


def _is_think_prefill(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    return str(message.get("content") or "").strip() == _THINK_PREFILL.strip()


def apply_thinking_controls(
    profile: LlmProfileConfig,
    messages: list[dict[str, Any]],
    *,
    disable_thinking: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Гасит reasoning: LM Studio/Qwen prefill; DeepSeek thinking.type=disabled."""
    if not disable_thinking:
        return list(messages), {}
    extra: dict[str, Any] = {}
    out = list(messages)
    if is_deepseek_base_url(profile.base_url):
        # DeepSeek V4: thinking по умолчанию включён — для JSON-извлечения выключаем.
        extra["thinking"] = {"type": "disabled"}
        return out, extra
    if is_local_base_url(profile.base_url):
        # /v1/chat/completions в LM Studio: none выключает thinking.
        extra["reasoning_effort"] = "none"
    if "qwen" in (profile.model or "").lower() and (not out or not _is_think_prefill(out[-1])):
        out.append({"role": "assistant", "content": _THINK_PREFILL})
    return out, extra


def relax_rejected_payload(payload: dict[str, Any], body: str = "") -> dict[str, Any] | None:
    """Снимает одно необязательное поле после HTTP 400/422.

    response_format снимается раньше reasoning_effort: повтор должен
    оставить выключенный thinking, иначе Qwen снова не укладывается в таймаут.
    """
    text = (body or "").lower()
    order: list[str] = []
    if any(tok in text for tok in ("response_format", "json_object", "json_schema")):
        order.append("response_format")
    if "reasoning" in text:
        order.append("reasoning_effort")
    if "thinking" in text:
        order.append("thinking")
    if any(tok in text for tok in ("think", "assistant", "message role", "last message")):
        order.append("prefill")
    if "tool" in text or "function" in text:
        order.append("tools")
    order.extend(("response_format", "reasoning_effort", "thinking", "prefill", "tools"))

    seen: set[str] = set()
    for name in order:
        if name in seen:
            continue
        seen.add(name)
        if name == "response_format" and "response_format" in payload:
            relaxed = dict(payload)
            relaxed.pop("response_format")
            return relaxed
        if name == "reasoning_effort" and "reasoning_effort" in payload:
            relaxed = dict(payload)
            relaxed.pop("reasoning_effort")
            return relaxed
        if name == "thinking" and "thinking" in payload:
            relaxed = dict(payload)
            relaxed.pop("thinking")
            return relaxed
        if name == "prefill":
            messages = list(payload.get("messages") or [])
            if messages and _is_think_prefill(messages[-1]):
                relaxed = dict(payload)
                relaxed["messages"] = messages[:-1]
                return relaxed
        if name == "tools" and payload.get("tools"):
            relaxed = dict(payload)
            relaxed.pop("tools", None)
            relaxed.pop("tool_choice", None)
            return relaxed
    return None


def _post_chat(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    try:
        with httpx.Client(timeout=timeout) as client:
            return client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(_timeout_message(timeout)) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Нет связи с моделью: {exc}") from exc


def test_connection(profile: LlmProfileConfig, api_key: str | None = None) -> dict[str, Any]:
    """Проверка доступности модели через chat.completions (OpenAI-compatible)."""
    key = _resolve_key(profile, api_key)

    payload = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                _chat_url(profile.base_url),
                headers=_auth_headers(key),
                json=payload,
            )
        if response.status_code >= 400:
            detail = response.text[:500]
            return {
                "ok": False,
                "model": profile.model,
                "error": f"HTTP {response.status_code}: {detail}",
            }

        data = response.json()
        content = ""
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")[:200]
        usage = data.get("usage") or {}
        return {
            "ok": True,
            "model": profile.model,
            "reply_preview": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        }
    except Exception as exc:  # noqa: BLE001 — отдаём текст ошибки в UI
        return {
            "ok": False,
            "model": profile.model,
            "error": str(exc),
        }


def chat_completion(
    profile: LlmProfileConfig,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    json_mode: bool | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    disable_thinking: bool = False,
) -> dict[str, Any]:
    """Вызов chat.completions. Возвращает content, tool_calls, usage, raw."""
    key = _resolve_key(profile, api_key)
    resolved_timeout = float(timeout) if timeout is not None else default_chat_timeout(profile)
    # При tool-calling JSON-mode обычно мешает — отключаем, если есть tools
    use_json = False if tools else (profile.supports_json_mode if json_mode is None else json_mode)
    sent_messages, extra = apply_thinking_controls(
        profile,
        messages,
        disable_thinking=disable_thinking,
    )
    payload: dict[str, Any] = {
        "model": profile.model,
        "messages": sent_messages,
        "temperature": temperature,
    }
    payload.update(extra)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if use_json:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    url = _chat_url(profile.base_url)
    headers = _auth_headers(key)
    response = _post_chat(url, headers, payload, resolved_timeout)
    # 400/422: по одному снимаем json_object, затем reasoning_effort, prefill и tools.
    # reasoning_effort остаётся на первом повторе — иначе Qwen снова думает до таймаута.
    for _ in range(3):
        if response.status_code not in {400, 422}:
            break
        relaxed = relax_rejected_payload(payload, response.text)
        if relaxed is None:
            break
        payload = relaxed
        response = _post_chat(url, headers, payload, resolved_timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {response.status_code}: {response.text[:800]}")

    data = response.json()
    content = ""
    tool_calls: list[dict[str, Any]] = []
    message: dict[str, Any] = {}
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "")
        raw_calls = message.get("tool_calls") or []
        if isinstance(raw_calls, list):
            tool_calls = raw_calls
    usage = data.get("usage") or {}
    return {
        "content": content,
        "tool_calls": tool_calls,
        "message": message,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        "raw": data,
    }


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _salvage_entities_relations(raw: str) -> dict[str, Any]:
    """Достаёт целые объекты из обрезанного JSON с entities/relations."""
    out: dict[str, Any] = {"entities": [], "relations": []}
    decoder = json.JSONDecoder()
    for key in ("entities", "relations"):
        marker = f'"{key}"'
        idx = raw.find(marker)
        if idx < 0:
            continue
        bracket = raw.find("[", idx)
        if bracket < 0:
            continue
        i = bracket + 1
        items: list[Any] = []
        while i < len(raw):
            while i < len(raw) and raw[i] in " \n\r\t,":
                i += 1
            if i >= len(raw) or raw[i] == "]":
                break
            try:
                obj, end = decoder.raw_decode(raw, i)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                items.append(obj)
            i = end
        out[key] = items
    if not out["entities"] and not out["relations"]:
        raise ValueError("Не удалось восстановить entities/relations из обрезанного JSON")
    return out


def extract_json_object(text: str) -> Any:
    """Достаёт JSON из ответа модели (с fence или сырой)."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Пустой ответ модели")
    # Снять markdown-обёртку ```json ... ```
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    elif raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Попытка вырезать первый объект/массив
        start_obj = raw.find("{")
        start_arr = raw.find("[")
        starts = [i for i in (start_obj, start_arr) if i >= 0]
        if not starts:
            raise
        start = min(starts)
        candidate = raw[start:]
        decoder = json.JSONDecoder()
        try:
            parsed, _ = decoder.raw_decode(candidate)
            return parsed
        except json.JSONDecodeError:
            pass
        # подрезать хвост
        for end in range(len(candidate), 0, -1):
            try:
                return json.loads(candidate[:end])
            except json.JSONDecodeError:
                continue
        # Обрезанный ответ LM Studio: спасти целые entities/relations
        if '"entities"' in candidate or '"relations"' in candidate:
            return _salvage_entities_relations(candidate)
        raise


def structured_completion(
    profile: LlmProfileConfig,
    *,
    system_prompt: str,
    user_prompt: str,
    repair: bool = True,
    api_key: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Запрос structured JSON + один repair-проход при ошибке парсинга."""
    messages = [
        {"role": "system", "content": system_prompt or "Return valid JSON only."},
        {"role": "user", "content": user_prompt},
    ]
    # Локальный LM Studio / DeepSeek: thinking раздувает ответ и ломает JSON.
    disable_thinking = is_local_base_url(profile.base_url) or is_deepseek_base_url(
        profile.base_url
    )
    resolved_timeout = float(timeout) if timeout is not None else default_chat_timeout(profile)
    first = chat_completion(
        profile,
        messages,
        json_mode=True,
        api_key=api_key,
        disable_thinking=disable_thinking,
        timeout=resolved_timeout,
    )
    raw_content = first["content"]
    if not str(raw_content or "").strip():
        raw_content = str((first.get("message") or {}).get("reasoning_content") or "")
    try:
        parsed = extract_json_object(raw_content)
        return {"data": parsed, "usage": first["usage"], "repaired": False, "raw_content": raw_content}
    except (ValueError, json.JSONDecodeError) as exc:
        if not repair:
            raise
        repair_messages = messages + [
            {"role": "assistant", "content": raw_content},
            {
                "role": "user",
                "content": (
                    "Ответ не является валидным JSON. "
                    f"Ошибка: {exc}. Верни ТОЛЬКО исправленный JSON-объект."
                ),
            },
        ]
        second = chat_completion(
            profile,
            repair_messages,
            json_mode=True,
            api_key=api_key,
            disable_thinking=disable_thinking,
            timeout=resolved_timeout,
        )
        repaired = second["content"]
        if not str(repaired or "").strip():
            repaired = str((second.get("message") or {}).get("reasoning_content") or "")
        parsed = extract_json_object(repaired)
        usage = {
            "prompt_tokens": first["usage"]["prompt_tokens"] + second["usage"]["prompt_tokens"],
            "completion_tokens": first["usage"]["completion_tokens"]
            + second["usage"]["completion_tokens"],
            "total_tokens": first["usage"]["total_tokens"] + second["usage"]["total_tokens"],
        }
        return {
            "data": parsed,
            "usage": usage,
            "repaired": True,
            "raw_content": repaired,
        }
