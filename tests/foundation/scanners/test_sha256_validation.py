"""The sha256-validation scanner.

Both duplicate styles are pinned as findings, while the canonical helper, SQL
validation, and ordinary code stay clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import sha256_validation


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_hex_alphabet_literal(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):\n'
                "    raise ValueError('bad')\n"
            )
        },
    )
    findings = sha256_validation.scan_sha256_validation()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/thing/job.py", 1)
    ]


def test_flags_sha256_hex_regex(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'import re\n_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")\n'
            )
        },
    )
    findings = sha256_validation.scan_sha256_validation()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/thing/job.py", 2)
    ]


def test_allows_canonical_helper(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "from edgar_sec.foundation.hashing import is_sha256_hex_digest\n"
                "if not is_sha256_hex_digest(digest):\n"
                "    raise ValueError('bad')\n"
            )
        },
    )
    assert sha256_validation.scan_sha256_validation() == []


def test_allows_sql_validation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "query = \"SELECT * FROM t WHERE regexp_full_match(col, '[0-9a-f]{64}')\"\n"
            )
        },
    )
    assert sha256_validation.scan_sha256_validation() == []


def test_allows_owner_module(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/hashing.py": (
                "def is_sha256_hex_digest(value):\n"
                '    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)\n'
            )
        },
    )
    assert sha256_validation.scan_sha256_validation() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/pipelines/thing/test_job.py": ("assert len(digest) == 64\n")},
    )
    assert sha256_validation.scan_sha256_validation() == []


def test_is_registered() -> None:
    from edgar_sec.foundation.scanners import ALL_SCANNERS

    assert sha256_validation.SCANNER in ALL_SCANNERS
    assert "sha256-validation" in {scanner.name for scanner in ALL_SCANNERS}
