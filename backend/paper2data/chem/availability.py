"""Проверка опциональных chem-зависимостей (RDKit, OPSIN)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def rdkit_available() -> bool:
    try:
        from rdkit import Chem  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 — любой сбой импорта = недоступно
        return False


@lru_cache(maxsize=1)
def opsin_available() -> bool:
    """OPSIN: pyopsin или CLI `opsin` в PATH."""
    try:
        import pyopsin  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import shutil

        return shutil.which("opsin") is not None
    except Exception:  # noqa: BLE001
        return False


def chem_status() -> dict[str, Any]:
    return {
        "rdkit": {
            "available": rdkit_available(),
            "note": (
                "RDKit установлен"
                if rdkit_available()
                else "RDKit не установлен — валидация/отрисовка в stub-режиме. pip install rdkit"
            ),
        },
        "opsin": {
            "available": opsin_available(),
            "note": (
                "OPSIN доступен локально"
                if opsin_available()
                else "OPSIN не найден — имя→структура через PubChem (онлайн) или stub"
            ),
        },
        "pubchem": {"available": True, "note": "PubChem PUG REST (онлайн)"},
        "crossref": {"available": True, "note": "Crossref REST API (онлайн)"},
    }
