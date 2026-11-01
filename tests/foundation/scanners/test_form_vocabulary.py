"""Mirrored unit tests for the form-vocabulary policy scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import form_vocabulary


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_private_cusip_regex(synthetic_repo: Path) -> None:
    """Verify private CUSIP regex literal is flagged outside common entities."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/beneficial_ownership/foo.py": (
                'import re\n_CUSIP_RE = re.compile(r"[0-9A-Za-z*@#]{8,9}")\n'
            )
        },
    )
    findings = form_vocabulary.scan_form_vocabulary()
    assert len(findings) == 1
    assert findings[0].path == "edgar_sec/engine/forms/beneficial_ownership/foo.py"
    assert findings[0].line == 2


def test_flags_dom_table_regex(synthetic_repo: Path) -> None:
    """Verify DOM table regex is flagged outside legacy ASCII unwrappers."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/beneficial_ownership/foo.py": (
                'import re\n_TABLE_RE = re.compile(r"</?TABLE>", re.I)\n'
            )
        },
    )
    findings = form_vocabulary.scan_form_vocabulary()
    assert len(findings) == 1
    assert findings[0].path == "edgar_sec/engine/forms/beneficial_ownership/foo.py"
    assert findings[0].line == 2


def test_flags_duplicate_unit_suffix_literal(synthetic_repo: Path) -> None:
    """Verify duplicate unit suffix literal is flagged outside common numbers."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/beneficial_ownership/foo.py": (
                'UNITS = ("shares of common stock", "ordinary shares")\n'
            )
        },
    )
    findings = form_vocabulary.scan_form_vocabulary()
    assert len(findings) == 1
    assert findings[0].path == "edgar_sec/engine/forms/beneficial_ownership/foo.py"
    assert findings[0].line == 1


def test_permits_canonical_owners(synthetic_repo: Path) -> None:
    """Verify canonical owner files and exempt paths pass cleanly."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/entities.py": (
                'import re\n_CUSIP_CLEAN_RE = re.compile(r"^[0-9A-Z*@#]{8,9}$")\n'
            ),
            "edgar_sec/engine/forms/common/numbers.py": (
                'UNITS = ("shares of common stock", "ordinary shares")\n'
            ),
            "edgar_sec/engine/forms/cover/tables/cleaner.py": (
                'import re\n_TABLE_RE = re.compile(r"</?TABLE>", re.I)\n'
            ),
        },
    )
    findings = form_vocabulary.scan_form_vocabulary()
    assert len(findings) == 0
