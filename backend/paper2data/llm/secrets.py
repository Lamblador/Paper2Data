"""Хранение API-ключей вне проекта: ~/.paper2data/secrets."""

from __future__ import annotations

import threading
from pathlib import Path

import yaml

from paper2data.core.paths import secrets_path

_lock = threading.RLock()


def _load() -> dict[str, str]:
    path = secrets_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def _save(data: dict[str, str]) -> None:
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=True)


def get_secret(ref: str) -> str | None:
    with _lock:
        return _load().get(ref)


def set_secret(ref: str, value: str) -> None:
    with _lock:
        data = _load()
        data[ref] = value
        _save(data)


def delete_secret(ref: str) -> None:
    with _lock:
        data = _load()
        if ref in data:
            del data[ref]
            _save(data)


def has_secret(ref: str) -> bool:
    value = get_secret(ref)
    return bool(value)


def secrets_file() -> Path:
    return secrets_path()
