from ml.public_benchmark_slabs_clean import (
    normalize_text,
    remove_exact_overlaps,
)


def test_normalize_text_collapses_case_and_whitespace():
    assert normalize_text("  Hello   WORLD  ") == "hello world"


def test_remove_exact_overlaps():
    rows = [
        {"text": "Keep me", "label": "safe"},
        {"text": " Duplicate  Text ", "label": "attack"},
    ]

    cleaned, removed = remove_exact_overlaps(
        rows,
        {"duplicate text"},
    )

    assert removed == 1
    assert len(cleaned) == 1
    assert cleaned[0]["text"] == "Keep me"
