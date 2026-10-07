from paper2data.extraction.chunks import merge_chunk_group, pack_chunks_to_context


def test_pack_merges_when_fits_in_context():
    chunks = [
        {
            "section_type": "abstract",
            "section_text": "A" * 1000,
            "tables_md": "",
            "figure_captions": "",
            "block_ids": [1],
            "blocks": [{"id": 1}],
        },
        {
            "section_type": "experimental",
            "section_text": "B" * 2000,
            "tables_md": "table",
            "figure_captions": "- fig",
            "block_ids": [2],
            "blocks": [{"id": 2}],
        },
        {
            "section_type": "results",
            "section_text": "C" * 1500,
            "tables_md": "",
            "figure_captions": "",
            "block_ids": [3],
            "blocks": [{"id": 3}],
        },
    ]
    packed = pack_chunks_to_context(chunks, context_size=52000, reserve_tokens_approx=12000)
    assert len(packed) == 1
    assert "Секция: abstract" in packed[0]["section_text"]
    assert "Секция: experimental" in packed[0]["section_text"]
    assert packed[0]["merged_sections"] == ["abstract", "experimental", "results"]
    assert packed[0]["block_ids"] == [1, 2, 3]


def test_pack_splits_when_over_budget():
    chunks = [
        {
            "section_type": "a",
            "section_text": "X" * 80_000,
            "tables_md": "",
            "figure_captions": "",
            "block_ids": [1],
            "blocks": [],
        },
        {
            "section_type": "b",
            "section_text": "Y" * 80_000,
            "tables_md": "",
            "figure_captions": "",
            "block_ids": [2],
            "blocks": [],
        },
    ]
    packed = pack_chunks_to_context(chunks, context_size=52000, reserve_tokens_approx=12000)
    assert len(packed) == 2
    assert merge_chunk_group([chunks[0]])["section_type"] == "a"
