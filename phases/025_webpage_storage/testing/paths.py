"""Canonical paths for Phase 025 document corpus and review artifacts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from defs.runtime.paths import FixturePaths, resolve_paths

_VERSION = re.compile(r"^v[0-9]+$")
_DOCUMENT_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1].joinpath("tests", "fixtures", "documents")
)


def _validate_version(version: str) -> str:
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("corpus version must match v<integer>")
    return version


def fixture_paths(fixture_id: str) -> FixturePaths:
    """Resolve one raw fixture ID through the shared runtime path contract."""

    return resolve_paths().fixture(fixture_id, dialect="sqlite")


def document_fixture_root() -> Path:
    """Return the tracked Phase 025 document-fixture directory."""

    return _DOCUMENT_FIXTURE_ROOT


def document_corpus_path(version: str = "v1") -> Path:
    """Return the tracked document corpus path for ``version``."""

    return (
        document_fixture_root()
        / f"document_corpus_{_validate_version(version)}.parquet"
    )


def document_manifest_path(version: str = "v1") -> Path:
    """Return the tracked document corpus manifest path for ``version``."""

    _validate_version(version)
    return document_fixture_root() / "manifest.json"


def find_document_corpus(version: str = "v1") -> Path:
    """Find a tracked corpus, failing clearly when it has not been promoted."""

    path = document_corpus_path(version)
    if not path.is_file():
        raise FileNotFoundError(f"document corpus not found: {path}")
    return path


def review_run_root(run_id: str | None = None) -> Path:
    """Return a generated review root without creating it."""

    resolved = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return resolve_paths().test_run_root(
        "webpage_storage", "document-reviews", resolved
    )


__all__ = [
    "document_corpus_path",
    "document_fixture_root",
    "document_manifest_path",
    "find_document_corpus",
    "fixture_paths",
    "review_run_root",
]
