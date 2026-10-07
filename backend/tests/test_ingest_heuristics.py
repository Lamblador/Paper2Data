"""Тесты эвристик секций и DOI (M1)."""

from __future__ import annotations

from paper2data.ingest.captions import classify_caption
from paper2data.ingest.doi import extract_dois, extract_first_doi, normalize_doi
from paper2data.ingest.esi import detect_esi_hints
from paper2data.ingest.sections import classify_heading, segment_blocks_by_headings


def test_normalize_doi():
    assert normalize_doi("10.1021/acs.inorgchem.0c00000") == "10.1021/acs.inorgchem.0c00000"
    assert normalize_doi("https://doi.org/10.1039/C9CC00000A.") == "10.1039/C9CC00000A"
    assert normalize_doi("doi: 10.1002/anie.202000000") == "10.1002/anie.202000000"
    assert normalize_doi("not-a-doi") is None


def test_extract_dois_from_bibliography_line():
    text = (
        "12. Smith et al. Chem. Commun. 2020, 56, 1. "
        "https://doi.org/10.1039/C9CC01234A"
    )
    assert extract_first_doi(text) == "10.1039/C9CC01234A"
    assert extract_dois("doi:10.1021/ja00001; also 10.1021/ja00002") == [
        "10.1021/ja00001",
        "10.1021/ja00002",
    ]


def test_classify_heading_types():
    assert classify_heading("1. Introduction").section_type == "introduction"
    assert classify_heading("ABSTRACT").section_type == "abstract"
    assert classify_heading("Materials and Methods").section_type == "experimental"
    assert classify_heading("Results and Discussion").section_type == "results"
    assert classify_heading("4. Conclusions").section_type == "conclusion"
    assert classify_heading("Acknowledgments").section_type == "acknowledgments"
    assert classify_heading("References").section_type == "references"
    assert classify_heading("Supporting Information").section_type == "esi"
    assert classify_heading("This is a long paragraph that should not match as heading at all because it has too many words for a section title really") is None


def test_segment_blocks_by_headings():
    blocks = [
        {"text": "Title of Paper", "page": 1},
        {"text": "Abstract", "page": 1},
        {"text": "We study Eu complexes.", "page": 1},
        {"text": "1. Introduction", "page": 1},
        {"text": "Lanthanides are useful.", "page": 2},
        {"text": "Experimental", "page": 2},
        {"text": "Synthesis details.", "page": 2},
        {"text": "References", "page": 3},
        {"text": "1. Someone, J. Chem. 2020.", "page": 3},
    ]
    sections = segment_blocks_by_headings(blocks)
    types = [s["section_type"] for s in sections]
    assert types[0] == "other"
    assert "abstract" in types
    assert "introduction" in types
    assert "experimental" in types
    assert "references" in types
    intro = next(s for s in sections if s["section_type"] == "introduction")
    assert intro["useful_default"] is False
    assert intro["page_start"] == 1


def test_classify_captions():
    fig = classify_caption("Figure 2. Emission spectra of 1 in MeCN.")
    assert fig is not None and fig.kind == "figure" and fig.label == "2"
    sch = classify_caption("Scheme 1 Synthesis of ligand L.")
    assert sch is not None and sch.kind == "scheme"
    tab = classify_caption("Table S1. Crystallographic data.")
    assert tab is not None and tab.kind == "table" and tab.label == "S1"


def test_detect_esi_hints():
    text = (
        "Additional data are given in the Supporting Information. "
        "See https://pubs.acs.org/doi/suppl/10.1021/acs.inorgchem.0c00000/suppl_file/esi.pdf"
    )
    hints = detect_esi_hints(text)
    kinds = {h["kind"] for h in hints}
    assert "phrase" in kinds
    assert "url" in kinds
