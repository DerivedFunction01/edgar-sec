"""Tests for the living-dates scanner's surfaces and exemptions."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.scanners.content.living_dates import (
    _mask_doc_lines,
    _python_surfaces,
    population,
    scan_tree,
)


def _write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_dated_comment_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", "# settled 2020-01-01\nX = 1\n")
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("pkg/mod.py", 1)]


def test_a_date_in_a_string_literal_passes(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", 'STAMP = "2020-01-01"\n')
    assert scan_tree(tmp_path) == []


def test_a_docstring_code_span_is_data(tmp_path: Path) -> None:
    source = '"""Expand ``2005Q3`` -> ``2005-07-01..2005-09-30``."""\n'
    _write(tmp_path, "pkg/mod.py", source)
    assert scan_tree(tmp_path) == []


def test_a_docstring_prose_date_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", '"""Settled on January 5, 2020."""\n')
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("pkg/mod.py", 1)]


def test_doc_lines_mask_fences_and_spans_but_not_prose() -> None:
    text = "prose\n```\nrun --on 2020-01-01\n```\n`x 2020-01-01` tail\n"
    masked = _mask_doc_lines(text)
    assert masked[2] == ""
    assert "2020-01-01" not in masked[4]
    assert masked[4].endswith(" tail")


def test_a_prose_date_beside_a_code_span_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "doc.md", "Settled 2020-01-01; run `tool` next.\n")
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("doc.md", 1)]


def test_gitignore_comment_rules(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", "# retired 2020-01-01\nfoo # 2020-01-01\n")
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [(".gitignore", 1)]


def test_config_comment_starts_at_an_unquoted_hash(tmp_path: Path) -> None:
    _write(tmp_path, "conf.toml", 'a = "x # 2020-01-01"\nb = 1 # set 2020-01-01\n')
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("conf.toml", 2)]


def test_script_comments_are_surfaces_and_strings_are_not(tmp_path: Path) -> None:
    _write(tmp_path, "ui.ts", '// settled 2020-01-01\nconst s = "2020-01-01";\n')
    findings = scan_tree(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("ui.ts", 1)]


def test_population_excludes_corpora_archives_and_the_date_home(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "uploads/spec.md", "Expires: December 31, 2026\n")
    _write(tmp_path, "tests/fixtures/corpus.md", "Dated 2020-01-01\n")
    _write(tmp_path, "run-logs/log.md", "Dated 2020-01-01\n")
    _write(tmp_path, "edgar_sec/foundation/text/dates.py", "# December 31, 2023\n")
    _write(tmp_path, "pkg/mod.py", "X = 1\n")
    names = [p.relative_to(tmp_path).as_posix() for p in population(tmp_path)]
    assert names == ["pkg/mod.py"]
    assert scan_tree(tmp_path) == []


def test_a_sanctioned_site_is_excused_by_fragment(tmp_path: Path) -> None:
    relpath = "edgar_sec/engine/document/page_markers/eligibility.py"
    _write(tmp_path, relpath, '# face ("... Prospectus - April 27, 2015")\n')
    assert scan_tree(tmp_path) == []
    _write(tmp_path, relpath, "# settled 2020-01-01\n")
    assert [(f.line) for f in scan_tree(tmp_path)] == [1]


def test_python_surfaces_skip_plain_strings() -> None:
    source = 'X = "2020-01-01"\n# noted\n'
    assert _python_surfaces(source) == [(2, "# noted")]
