"""Тесты M6: Crossref URL, SMILES stub-путь без RDKit."""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from paper2data.chem.crossref import CROSSREF_WORKS_BASE, crossref_works_url
from paper2data.chem.rdkit_tools import smiles_to_svg, validate_and_draw, validate_smiles
from paper2data.chem.availability import chem_status, rdkit_available


def test_crossref_works_url_building():
    url = crossref_works_url("10.1021/acs.inorgchem.0c00000")
    assert url.startswith(CROSSREF_WORKS_BASE + "/")
    assert "10.1021" in unquote(url)
    assert "acs.inorgchem.0c00000" in unquote(url)

    url2 = crossref_works_url("https://doi.org/10.1039/C9CC00000A.")
    assert unquote(url2).endswith("10.1039/C9CC00000A")

    with pytest.raises(ValueError):
        crossref_works_url("not-a-doi")


def test_validate_smiles_stub_or_rdkit():
    empty = validate_smiles("")
    assert empty["ok"] is False
    assert empty["valid"] is False

    result = validate_smiles("CCO")
    assert "backend" in result
    if rdkit_available():
        assert result["backend"] == "rdkit"
        assert result["valid"] is True
        assert result.get("canonical_smiles")
    else:
        assert result["backend"] == "stub"
        assert result.get("stub") is True
        assert result["valid"] is True  # простой stub принимает CCO
        assert "RDKit" in (result.get("note") or "")

    bad = validate_smiles("   ")
    assert bad["valid"] is False


def test_smiles_to_svg_graceful_without_rdkit():
    if rdkit_available():
        out = smiles_to_svg("CCO")
        assert out["ok"] is True
        assert out.get("svg") and "<svg" in out["svg"].lower()
    else:
        out = smiles_to_svg("CCO")
        assert out["backend"] == "stub"
        assert out.get("svg") and "RDKit" in out["svg"]
        assert out["ok"] is False


def test_validate_and_draw_combo():
    combo = validate_and_draw(smiles="c1ccccc1")
    assert "smiles_check" in combo
    assert "svg" in combo
    assert "rdkit_available" in combo


def test_chem_status_shape():
    status = chem_status()
    assert "rdkit" in status
    assert "opsin" in status
    assert "pubchem" in status
    assert "crossref" in status
    assert isinstance(status["rdkit"]["available"], bool)
