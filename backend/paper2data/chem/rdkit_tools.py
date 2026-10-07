"""Валидация SMILES/InChI и 2D SVG через RDKit (graceful degrade)."""

from __future__ import annotations

from typing import Any

from paper2data.chem.availability import rdkit_available


def validate_smiles(smiles: str) -> dict[str, Any]:
    """Проверка SMILES. Без RDKit — синтаксический stub."""
    raw = (smiles or "").strip()
    if not raw:
        return {
            "ok": False,
            "valid": False,
            "smiles": raw,
            "backend": "none",
            "error": "Пустой SMILES",
        }

    if not rdkit_available():
        # Минимальный stub: непустая строка без пробелов в середине считается «возможно валидной»
        looks_ok = " " not in raw and any(c.isalpha() for c in raw)
        return {
            "ok": looks_ok,
            "valid": looks_ok,
            "smiles": raw,
            "canonical_smiles": None,
            "backend": "stub",
            "stub": True,
            "error": None if looks_ok else "SMILES выглядит некорректно (stub без RDKit)",
            "note": "RDKit не установлен — полная валидация недоступна",
        }

    from rdkit import Chem

    mol = Chem.MolFromSmiles(raw)
    if mol is None:
        return {
            "ok": False,
            "valid": False,
            "smiles": raw,
            "backend": "rdkit",
            "error": "RDKit не смог разобрать SMILES",
        }
    can = Chem.MolToSmiles(mol)
    return {
        "ok": True,
        "valid": True,
        "smiles": raw,
        "canonical_smiles": can,
        "num_atoms": mol.GetNumAtoms(),
        "backend": "rdkit",
        "stub": False,
        "error": None,
    }


def validate_inchi(inchi: str) -> dict[str, Any]:
    raw = (inchi or "").strip()
    if not raw:
        return {
            "ok": False,
            "valid": False,
            "inchi": raw,
            "backend": "none",
            "error": "Пустой InChI",
        }

    if not rdkit_available():
        looks_ok = raw.upper().startswith("INCHI=") or raw.upper().startswith("INCHIKEY=")
        return {
            "ok": looks_ok,
            "valid": looks_ok,
            "inchi": raw,
            "backend": "stub",
            "stub": True,
            "error": None if looks_ok else "InChI должен начинаться с InChI= (stub без RDKit)",
            "note": "RDKit не установлен — полная валидация недоступна",
        }

    from rdkit import Chem

    mol = Chem.MolFromInchi(raw)
    if mol is None:
        return {
            "ok": False,
            "valid": False,
            "inchi": raw,
            "backend": "rdkit",
            "error": "RDKit не смог разобрать InChI",
        }
    return {
        "ok": True,
        "valid": True,
        "inchi": raw,
        "smiles": Chem.MolToSmiles(mol),
        "backend": "rdkit",
        "stub": False,
        "error": None,
    }


def smiles_to_svg(smiles: str, *, width: int = 280, height: int = 200) -> dict[str, Any]:
    """2D SVG для карточки Component. Без RDKit — понятный stub."""
    raw = (smiles or "").strip()
    if not raw:
        return {
            "ok": False,
            "svg": None,
            "backend": "none",
            "error": "Пустой SMILES",
        }

    if not rdkit_available():
        escaped = (
            raw.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        stub_svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<rect width="100%" height="100%" fill="#fffdf8" stroke="#c9d2dc"/>'
            f'<text x="12" y="28" font-size="12" fill="#5d6b7c">RDKit не установлен</text>'
            f'<text x="12" y="52" font-size="11" fill="#1c2430">{escaped[:48]}</text>'
            f"</svg>"
        )
        return {
            "ok": False,
            "svg": stub_svg,
            "backend": "stub",
            "stub": True,
            "note": "Установите RDKit для отрисовки структуры: pip install rdkit",
            "error": "RDKit недоступен",
        }

    from rdkit import Chem
    from rdkit.Chem import Draw
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(raw)
    if mol is None:
        return {
            "ok": False,
            "svg": None,
            "backend": "rdkit",
            "error": "Невалидный SMILES — отрисовка невозможна",
        }

    try:
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()
    except Exception:  # noqa: BLE001 — запасной путь через Draw
        svg = Draw.MolsToGridImage([mol], useSVG=True, molsPerRow=1, subImgSize=(width, height))
        if not isinstance(svg, str):
            return {
                "ok": False,
                "svg": None,
                "backend": "rdkit",
                "error": "Не удалось получить SVG",
            }

    return {
        "ok": True,
        "svg": svg,
        "backend": "rdkit",
        "stub": False,
        "error": None,
    }


def validate_and_draw(smiles: str | None = None, inchi: str | None = None) -> dict[str, Any]:
    """Комбо для UI: валидация + SVG (если есть SMILES)."""
    result: dict[str, Any] = {"ok": False}
    if smiles:
        result["smiles_check"] = validate_smiles(smiles)
        result["svg"] = smiles_to_svg(smiles)
        result["ok"] = bool(result["smiles_check"].get("valid"))
    if inchi:
        result["inchi_check"] = validate_inchi(inchi)
        if not smiles and result["inchi_check"].get("smiles"):
            derived = result["inchi_check"]["smiles"]
            result["smiles_check"] = validate_smiles(derived)
            result["svg"] = smiles_to_svg(derived)
        result["ok"] = result.get("ok") or bool(result["inchi_check"].get("valid"))
    if not smiles and not inchi:
        result["error"] = "Укажите smiles или inchi"
    result["rdkit_available"] = rdkit_available()
    return result
