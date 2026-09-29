"""Unit tests for edgar_sec.engine.forms.checkmarks._yesno.

The Yes/No pair normalizer canonicalizes a line only when *both* opposite
answers are explicitly marked on it, and the rewrite is narrow: the marked
glyph is replaced with the canonical bracket form (``[X]`` checked, ``[ ]``
unchecked) so downstream matching sees one spelling. A mark whose own delimiter
style differs from the canonical bracket (``/x/``, ``|x|``) is left alone,
because rewriting it would change the delimiter style the filing used. And a
single mark is never rewritten: it is evidence about one answer rather than a
pair.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.checkmarks._yesno import (
    RE_SEPARATOR_LINE,
    normalize_yes_no_pair_line,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # both marks *after* the answer: the checked glyph becomes canonical
        ("YES [x]   NO [ ]", "YES [X]   NO [ ]"),
        # both marks *before*: the pair already reads canonically, untouched
        ("[x] YES   [ ] NO", "[x] YES   [ ] NO"),
        # one mark before, one after: still a pair, checked glyph canonicalized
        ("[x] YES    NO [ ]", "[X] YES    NO [ ]"),
        ("YES [x]    [ ] NO", "YES [X]    [ ] NO"),
        # a single mark is evidence about one answer, never rewritten
        ("YES [x]  NO", "YES [x]  NO"),
        ("YES    NO [x]", "YES    NO [x]"),
        # the same answer twice is not a pair
        ("YES   YES", "YES   YES"),
        # prose that merely mentions both answers is not a marked pair
        ("YES x NO", "YES x NO"),
        ("YES /x/ NO", "YES /x/ NO"),
        ("YES |x| NO", "YES |x| NO"),
    ],
)
def test_pair_canonicalization_contract(line: str, expected: str) -> None:
    assert normalize_yes_no_pair_line(line) == expected


def test_rewritten_marks_are_always_the_canonical_glyphs() -> None:
    """Whatever the source glyph was, the pair rewrite emits [X] / [ ]."""
    rewritten = normalize_yes_no_pair_line("YES _x_   NO _ _")
    assert "[X]" in rewritten
    assert "[ ]" in rewritten


def test_line_without_both_answers_passes_through() -> None:
    for line in (
        "FILED AS LARGE ACCELERATED FILER: YES",
        "IF YES, INDICATE BY CHECK MARK",
        "SHELL COMPANY: NO",
    ):
        assert normalize_yes_no_pair_line(line) == line


def test_a_line_without_yes_and_no_is_untouched_even_if_marked() -> None:
    line = "[x] LARGE ACCELERATED FILER"
    assert normalize_yes_no_pair_line(line) == line


def test_separator_lines_match() -> None:
    for line in ("---", "===", "________", "   - - -   "):
        assert RE_SEPARATOR_LINE.match(line), line
    assert not RE_SEPARATOR_LINE.match("Large accelerated filer")
