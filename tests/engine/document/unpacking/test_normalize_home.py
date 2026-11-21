"""Pins for the bundle-type normalize home (Wave 2B, item P5).
The form normalizer lives in ``domain.document.canonical``;
the bundle unpacker binds it under its own name.
"""

from __future__ import annotations

from edgar_sec.domain.document.canonical import normalize_form
from edgar_sec.engine.document.unpacking import streaming


def test_binding_is_the_canonical_home() -> None:
    assert streaming._normalize_bundle_type is normalize_form


def test_normalize_verdicts() -> None:
    assert streaming._normalize_bundle_type("abc") == "ABC"
    assert streaming._normalize_bundle_type("  a  b\tc ") == "A B C"
    for value in ("10-k", "exhibit 21", "S-1/A", ""):
        assert streaming._normalize_bundle_type(value) == normalize_form(value)
