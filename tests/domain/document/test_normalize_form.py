"""Pins for the homed document helpers and their diverged former copies.
normalize_form and normalized_suffix are homed; the diverged _normalize_form
copies keep their behavior, pinned as the delta a cure must not absorb.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.document.canonical import normalize_form
from edgar_sec.domain.document.path_facts import normalized_suffix
from edgar_sec.engine.forms.form_drs.analysis import _normalize_form as drs_form
from edgar_sec.pipelines.document_planning.profiles import (
    _normalize_form as profiles_form,
)


def test_normalize_form_collapses_whitespace_and_uppercases() -> None:
    assert normalize_form("  some   form ") == "SOME FORM"
    assert normalize_form("xyz") == "XYZ"


def test_normalized_suffix_casefolds_and_unifies_separators() -> None:
    assert normalized_suffix("dir\\FILE.HTM") == ".htm"
    assert normalized_suffix(" dir/report.PDF ") == ".pdf"
    assert normalized_suffix("noext") == ""


def test_drs_copy_does_not_collapse_inner_whitespace() -> None:
    assert drs_form("a  b") == "A  B"
    assert normalize_form("a  b") == "A B"


def test_profiles_copy_passes_star_through_and_rejects_empty() -> None:
    assert profiles_form("*") == "*"
    with pytest.raises(ValueError):
        profiles_form("   ")
