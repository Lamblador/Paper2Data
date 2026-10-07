"""Имя → структура: OPSIN (локально) и/или PubChem PUG REST."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any
from urllib.parse import quote

import httpx

from paper2data.chem.availability import opsin_available

PUBCHEM_PROP_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/"
    "IsomericSMILES,CanonicalSMILES,InChI,IUPACName,Title/JSON"
)


def _opsin_to_smiles(name: str) -> dict[str, Any] | None:
    if not opsin_available():
        return None
    try:
        import pyopsin

        smiles = pyopsin.parse(name) if hasattr(pyopsin, "parse") else None
        if not smiles and hasattr(pyopsin, "Opsin"):
            smiles = pyopsin.Opsin().parseToSmiles(name)
        if smiles:
            return {
                "smiles": str(smiles).strip(),
                "source": "opsin",
                "name": name,
            }
    except Exception:  # noqa: BLE001
        pass

    opsin_bin = shutil.which("opsin")
    if not opsin_bin:
        return None
    try:
        proc = subprocess.run(
            [opsin_bin, "-osmi"],
            input=name,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        out = (proc.stdout or "").strip().splitlines()
        if proc.returncode == 0 and out and out[0].strip():
            return {"smiles": out[0].strip(), "source": "opsin_cli", "name": name}
    except Exception:  # noqa: BLE001
        return None
    return None


def _pubchem_lookup(name: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    url = PUBCHEM_PROP_URL.format(name=quote(name, safe=""))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Paper2Data/0.1 (local)"})
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            return {
                "error": f"PubChem HTTP {response.status_code}",
                "source": "pubchem",
                "name": name,
            }
        data = response.json()
        props = (data.get("PropertyTable") or {}).get("Properties") or []
        if not props:
            return None
        row = props[0]
        smiles = row.get("IsomericSMILES") or row.get("CanonicalSMILES")
        return {
            "smiles": smiles,
            "inchi": row.get("InChI"),
            "iupac": row.get("IUPACName"),
            "title": row.get("Title"),
            "cid": row.get("CID"),
            "source": "pubchem",
            "name": name,
            "needs_confirm": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "pubchem", "name": name}


def name_to_structure(
    name: str,
    *,
    prefer_opsin: bool = True,
    use_pubchem: bool = True,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Предлагает SMILES по химическому названию. Результат — на подтверждение."""
    query = (name or "").strip()
    if not query:
        return {"ok": False, "error": "Пустое название", "proposals": []}

    proposals: list[dict[str, Any]] = []
    errors: list[str] = []

    if prefer_opsin:
        opsin_hit = _opsin_to_smiles(query)
        if opsin_hit and opsin_hit.get("smiles"):
            proposals.append({**opsin_hit, "needs_confirm": True})
        elif not opsin_available():
            errors.append("OPSIN не установлен (опционально: pip install pyopsin)")

    if use_pubchem and not proposals:
        pc = _pubchem_lookup(query, timeout=timeout)
        if pc is None:
            errors.append("PubChem: ничего не найдено")
        elif pc.get("error"):
            errors.append(str(pc["error"]))
        elif pc.get("smiles"):
            proposals.append(pc)
        else:
            errors.append("PubChem: ответ без SMILES")
    elif use_pubchem and proposals:
        # Дополнительный кандидат из PubChem
        pc = _pubchem_lookup(query, timeout=timeout)
        if pc and pc.get("smiles") and not pc.get("error"):
            if pc["smiles"] != proposals[0].get("smiles"):
                proposals.append(pc)

    return {
        "ok": bool(proposals),
        "name": query,
        "proposals": proposals,
        "needs_confirm": True,
        "opsin_available": opsin_available(),
        "errors": errors,
        "note": "Выберите предложение и подтвердите запись SMILES в атрибуты узла",
    }
