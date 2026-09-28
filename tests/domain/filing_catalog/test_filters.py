"""Unit tests for domain.filing_catalog.filters: shared filter vocabulary.

The vocabulary lives in Layer 1 because deterministic planning and the Stage B
selection policy both need it, and the layer graph forbids the lower layer from
reaching up. These tests pin the normalization that both consumers rely on.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.filing_catalog.filters import (
    AMENDMENT_POLICIES,
    DEFAULT_AMENDMENT,
    DEFAULT_DOCUMENT_SUFFIXES,
    normalize_suffixes,
)


def test_amendment_vocabulary_is_closed() -> None:
    assert AMENDMENT_POLICIES == ("both", "original", "amendments")
    assert DEFAULT_AMENDMENT in AMENDMENT_POLICIES
    assert DEFAULT_DOCUMENT_SUFFIXES == ()


def test_normalize_suffixes_lowercases_and_strips_dots() -> None:
    assert normalize_suffixes([".TXT", "xml", "  Htm "]) == ("txt", "xml", "htm")


def test_normalize_suffixes_deduplicates_but_preserves_order() -> None:
    """Order participates in the plan identity hash, so it must be stable."""
    assert normalize_suffixes(("htm", "txt", ".htm", "Htm")) == ("htm", "txt")


def test_normalize_suffixes_drops_empty_tokens() -> None:
    assert normalize_suffixes(("", "  ", ".")) == ()


def test_normalize_suffixes_rejects_quote_shaped_input() -> None:
    """v1 interpolated the suffix into a SQL literal; the allowlist is the fix."""
    for hostile in ("a'; DROP TABLE t; --", "--", "a b", "a/b", "a;b"):
        with pytest.raises(ValueError, match="invalid document suffix"):
            normalize_suffixes((hostile,))


def test_normalize_suffixes_rejects_non_string_entries() -> None:
    with pytest.raises(ValueError, match="suffix must be a string"):
        normalize_suffixes((None,))  # type: ignore[arg-type]
