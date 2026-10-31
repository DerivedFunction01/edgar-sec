"""Tests for the prose-length scanner's counting and exemptions."""

from __future__ import annotations

import pytest

from edgar_sec.foundation.scanners.prose_length import (
    _comment_findings,
    _comment_runs,
    _docstring_findings,
    content_lines,
    scan_prose_length,
)


def _findings(source: str, path: str = "edgar_sec/x.py"):
    return _docstring_findings(path, source) + _comment_findings(path, source)


def test_a_module_docstring_within_the_cap_passes() -> None:
    assert _findings('"""Summary.\n\nOne.\nTwo.\nThree.\n"""\n') == []


def test_a_module_docstring_over_the_cap_is_reported() -> None:
    findings = _findings('"""Summary.\n\nOne.\nTwo.\nThree.\nFour.\n"""\n')
    assert [(f.line, "module" in f.message) for f in findings] == [(1, True)]


def test_a_module_docstring_allows_one_more_line_than_a_function() -> None:
    four = '"""Summary.\n\nOne.\nTwo.\nThree.\n"""\n'
    nested = "def f():\n    " + four.replace("\n", "\n    ")
    assert not [f for f in _findings(four) if "module" in f.message]
    assert [f for f in _findings(nested) if "functiondef" in f.message]


def test_tests_get_tighter_caps_than_source() -> None:
    three = '"""Summary.\n\nOne.\nTwo.\n"""\n'
    nested = "def test_f():\n    " + three.replace("\n", "\n    ")
    assert _findings(nested, "tests/x/test_f.py") != []
    assert not _findings(nested, "edgar_sec/x.py")


def test_a_hash_inside_a_string_is_not_a_comment() -> None:
    source = 'SQL = "SELECT 1 -- not a comment"\n# real\n'
    assert _comment_runs(source) == [(2, 1)]


def test_a_multiline_sql_literal_is_not_a_comment_run() -> None:
    source = 'SQL = """\n-- leading marker\n-- another\n"""\n'
    assert _comment_runs(source) == []


def test_adjacent_comment_lines_form_one_run() -> None:
    assert _comment_runs("# one\n# two\nx = 1\n# three\n") == [(1, 2), (4, 1)]


def test_trailing_comments_are_counted_individually() -> None:
    labelled = "".join(f'"\\u{i:04x}",  # LABEL {i}\n' for i in range(6))
    assert _comment_runs(labelled) == []


def test_a_comment_run_over_the_cap_is_reported() -> None:
    findings = _findings("# one\n# two\n# three\n# four\nx = 1\n")
    assert [(f.line, f.message) for f in findings] == [
        (1, "comment run is 4 lines (cap 3)")
    ]


def test_check_py_module_docstring_is_exempt_as_help_text() -> None:
    source = '"""Usage.\n\n' + "".join(f"Line {i}.\n" for i in range(8)) + '"""\n'
    assert _findings(source, "check.py") == []


def test_unparsable_source_is_skipped_rather_than_reported() -> None:
    assert _docstring_findings("edgar_sec/x.py", "def broken(:\n") == []


def test_content_lines_excludes_delimiters_and_blanks() -> None:
    lines = ['"""Summary.', "", "Body one.", "Body two.", '"""']
    assert content_lines(lines, 1, 5) == 3


def test_a_single_line_docstring_counts_as_one() -> None:
    assert content_lines(['"""Just this."""'], 1, 1) == 1


def test_the_repository_itself_has_no_violations() -> None:
    assert scan_prose_length() == []
