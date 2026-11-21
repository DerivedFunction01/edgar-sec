"""The whole-file-read scanner.
Both directions are pinned: a read consumed by a digest is caught, and a read handed
to a JSON parser is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import whole_file_read


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_read_bytes_inside_a_hash(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "import hashlib\n"
                "digest = hashlib.sha256(path.read_bytes()).hexdigest()\n"
            )
        },
    )
    findings = whole_file_read.scan_whole_file_reads()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/thing/job.py", 2)
    ]


def test_flags_a_hash_constructor_around_a_nested_read(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "import hashlib\ndigest = hashlib.sha256(_resolve(path).read_bytes())\n"
            )
        },
    )
    assert whole_file_read.scan_whole_file_reads()


def test_allows_a_whole_file_read_handed_to_a_parser(
    synthetic_repo: Path,
) -> None:
    """The JSON parse reads a small payload whole on purpose."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/registry.py": (
                "import json\nreport = json.loads(source.raw_path.read_bytes())\n"
            )
        },
    )
    assert whole_file_read.scan_whole_file_reads() == []


def test_allows_streaming_hashing(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "from edgar_sec.foundation.hashing import file_sha256\n"
                "digest = file_sha256(path)\n"
            )
        },
    )
    assert whole_file_read.scan_whole_file_reads() == []


def test_does_not_borrow_a_read_from_another_line(
    synthetic_repo: Path,
) -> None:
    """A hash several statements away must not claim an unrelated read."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "import hashlib\n"
                "payload = path.read_bytes()\n"
                "digest = hashlib.sha256(other_payload).hexdigest()\n"
            )
        },
    )
    assert whole_file_read.scan_whole_file_reads() == []


def test_ignores_commented_and_scanner_sources(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                "# digest = hashlib.sha256(path.read_bytes())\ndigest = 1\n"
            ),
            "edgar_sec/foundation/scanners/thing.py": (
                "PATTERN = r'sha256\\([^)]*\\.read_bytes\\(\\)'\n"
            ),
            "edgar_sec/foundation/hashing.py": "def f(): return path.read_bytes()\n",
        },
    )
    assert whole_file_read.scan_whole_file_reads() == []


def test_is_registered() -> None:
    from edgar_sec.foundation.scanners import ALL_SCANNERS

    assert whole_file_read.SCANNER in ALL_SCANNERS
    assert "whole-file-read" in {scanner.name for scanner in ALL_SCANNERS}
