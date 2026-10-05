"""The json-io scanner.
Two failures are policed: a second serialisation producing disagreeing hashes, and
a non-atomic write a crash can leave truncated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import json_io


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_redundant_canonical_json_definition(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def canonical_json(value):\n    return None\n"},
    )
    findings = json_io.scan_json_io()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_non_atomic_json_dump(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "def write(payload, fh):\n    json.dump(payload, fh)\n"
            )
        },
    )
    assert json_io.scan_json_io()


def test_flags_write_text_of_dumps(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "def write(path, payload):\n    path.write_text(json.dumps(payload))\n"
            )
        },
    )
    assert json_io.scan_json_io()


def test_allows_primitive_owners(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/serialization.py": (
                "def canonical_json(value):\n    return None\n"
            ),
            "edgar_sec/infra/storage/atomic.py": (
                "def write(fh, payload):\n    json.dump(payload, fh)\n"
            ),
        },
    )
    assert json_io.scan_json_io() == []


def test_allows_shared_helper_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "from edgar_sec.foundation.serialization import canonical_json\n"
                "def render(value):\n    return canonical_json(value)\n"
            )
        },
    )
    assert json_io.scan_json_io() == []


def test_hint_points_at_atomic_writer(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "def write(payload, fh):\n    json.dump(payload, fh)\n"
            )
        },
    )
    assert "atomic_write_json" in json_io.scan_json_io()[0].hint
