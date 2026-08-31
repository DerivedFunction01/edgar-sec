"""Contract tests for shared entity normalization primitives."""

from defs.entities import (
    STATE_NAMES,
    STATE_POSTAL_CODES,
    clean_entity_name,
    entity_name_tokens,
    strip_jurisdiction,
)


def test_shared_jurisdiction_vocabulary_covers_codes_and_names() -> None:
    assert "DE" in STATE_POSTAL_CODES
    assert "PR" in STATE_POSTAL_CODES
    assert "delaware" in STATE_NAMES
    assert "puerto rico" in STATE_NAMES


def test_entity_cleaning_and_tokens_remove_jurisdiction_and_legal_form() -> None:
    assert strip_jurisdiction("Plantronics, Inc. /CA/") == "Plantronics, Inc."
    assert clean_entity_name("  Plantronics, Inc. /CA/  ") == "Plantronics, Inc."
    assert entity_name_tokens("The Plantronics, Inc. /CA/") == ["plantronics"]
