"""Unit tests for canonical forward-looking disclosure vocabulary."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import (
    FORWARD_LOOKING_PHRASES,
    FORWARD_LOOKING_VERBS,
)


def test_forward_looking_phrases_contains_standard_captions() -> None:
    assert "forward-looking statements" in FORWARD_LOOKING_PHRASES
    assert "forward looking statements" in FORWARD_LOOKING_PHRASES
    assert "safe harbor" in FORWARD_LOOKING_PHRASES
    assert "cautionary note" in FORWARD_LOOKING_PHRASES


def test_forward_looking_verbs_contains_inflections() -> None:
    for verb in ("expects", "believes", "anticipates", "estimates", "intends"):
        assert verb in FORWARD_LOOKING_VERBS
