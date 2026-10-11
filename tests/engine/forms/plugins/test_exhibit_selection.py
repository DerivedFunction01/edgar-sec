"""Tests for exhibit selection and compilation."""

from edgar_sec.domain.forms.exhibits.packs import ex3_1, ex31_i
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    CompiledExhibitPack,
    _compile_pack,
    _get_compiled_pack,
    probe_exhibit_header,
)


def test_compile_pack():
    """Verify pack compilation produces compiled patterns."""
    compiled = _compile_pack(ex3_1.PACK)
    assert compiled.pack_id == "ex3_1"
    assert isinstance(compiled, CompiledExhibitPack)
    assert compiled.title_pattern is not None
    assert compiled.primary_pattern is not None


def test_compiled_pack_cache():
    """Verify compiled packs are cached by pack_id."""
    compiled1 = _get_compiled_pack("test_pack", ex3_1.PACK)
    compiled2 = _get_compiled_pack("test_pack", ex3_1.PACK)
    assert compiled1 is compiled2


def test_probe_exhibit_header():
    """Verify probe detects line-anchored exhibit codes."""
    text = """EXHIBIT 3.1

ARTICLES OF INCORPORATION
This document contains the Articles of Incorporation."""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is not None
    assert match.exhibit_identity.code == "3.1"
    assert match.evidence_tier == "direct_designator"


def test_probe_exhibitsensitive():
    """Verify probe is case-insensitive."""
    text = """exhibit 3.1

Articles of Incorporation"""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is not None
    assert match.exhibit_identity.code == "3.1"


def test_probe_without_code():
    """Verify probe returns None when no exhibit code present."""
    text = """ARTICLES OF INCORPORATION
This document contains the Articles of Incorporation."""

    lines = tuple(text.split("\n", 25))
    match = probe_exhibit_header(text, lines)

    assert match is None
