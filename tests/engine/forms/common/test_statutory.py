"""Unit tests for engine common statutory regexes."""

from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)


def test_header_leak_and_statutory_artifact_matching():
    """Verify detection of header leaks and statutory artifacts."""
    assert bool(HEADER_LEAK_RE.search("date of original filing"))
    assert bool(STATUTORY_PAGE_ARTIFACT_RE.search("see instruction 6 for procedure"))
