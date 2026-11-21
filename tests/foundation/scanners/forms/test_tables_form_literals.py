"""Tables form-literal scanner: scoped to engine/tables, quoted only."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners.forms import tables_form_literals


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_quoted_form_literal_under_engine_tables(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/core/subjects/profiles.py": 'SCOPE = "10-K"\n'
        },
    )
    findings = tables_form_literals.scan_tables_form_literals()
    assert [f.path for f in findings] == [
        "edgar_sec/engine/tables/extraction/core/subjects/profiles.py"
    ]


def test_allows_literals_outside_engine_tables(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/forms/cover.py": 'SCOPE = "10-K"\n'},
    )
    assert tables_form_literals.scan_tables_form_literals() == []


def test_allows_exhibit_data_and_stratum_codes(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/tables/extraction/core/subjects/profiles.py": (
                'LINK = "EX-13"\nSTRATUM = "B"\n# the annual form\n'
            )
        },
    )
    assert tables_form_literals.scan_tables_form_literals() == []
