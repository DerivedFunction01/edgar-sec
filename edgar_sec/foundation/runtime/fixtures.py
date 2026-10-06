"""Shared fixture locations and manifest envelope validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURES_DIR = "fixtures"
FIXTURE_MANIFEST_NAME = "manifest.json"
FIXTURE_MANIFEST_VERSION = 1

_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class FixtureManifestError(ValueError):
    """A fixture manifest does not satisfy the shared envelope."""


def validate_fixture_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not _COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def fixtures_root(artifacts_root: Path | str, dataset: str) -> Path:
    dataset = validate_fixture_component(dataset, "dataset")
    return Path(artifacts_root) / dataset / FIXTURES_DIR


@dataclass(frozen=True, slots=True)
class FixturePaths:
    artifacts_root: Path
    dataset: str
    fixture_id: str
    storage_filename: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        validate_fixture_component(self.dataset, "dataset")
        validate_fixture_component(self.fixture_id, "fixture_id")
        validate_fixture_component(self.storage_filename, "storage filename")

    @property
    def root(self) -> Path:
        return fixtures_root(self.artifacts_root, self.dataset) / self.fixture_id

    @property
    def manifest_path(self) -> Path:
        return self.root / FIXTURE_MANIFEST_NAME

    @property
    def storage_path(self) -> Path:
        return self.root / self.storage_filename


def fixture_paths(
    artifacts_root: Path | str,
    dataset: str,
    fixture_id: str,
    storage_filename: str,
) -> FixturePaths:
    return FixturePaths(Path(artifacts_root), dataset, fixture_id, storage_filename)


@dataclass(frozen=True, slots=True)
class FixtureManifestEnvelope:
    fixture_kind: str
    fixture_id: str
    storage_format: str
    storage_path: str
    created_at: str
    updated_at: str
    details: Mapping[str, Any]
    manifest_version: int = FIXTURE_MANIFEST_VERSION

    def __post_init__(self) -> None:
        validate_fixture_component(self.fixture_id, "fixture_id")
        validate_fixture_component(self.storage_path, "storage path")
        if not isinstance(self.fixture_kind, str) or not self.fixture_kind:
            raise FixtureManifestError("fixture kind is required")
        if not isinstance(self.storage_format, str) or not self.storage_format:
            raise FixtureManifestError("fixture kind and storage format are required")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise FixtureManifestError("fixture timestamps are required")
        if not isinstance(self.updated_at, str) or not self.updated_at:
            raise FixtureManifestError("fixture timestamps are required")
        if self.manifest_version != FIXTURE_MANIFEST_VERSION:
            raise FixtureManifestError(
                f"unsupported fixture manifest version: {self.manifest_version}"
            )
        if not isinstance(self.details, Mapping):
            raise FixtureManifestError("fixture details must be an object")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "fixture_kind": self.fixture_kind,
            "manifest_version": self.manifest_version,
            "fixture_id": self.fixture_id,
            "storage": {"format": self.storage_format, "path": self.storage_path},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "details": dict(self.details),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FixtureManifestEnvelope:
        try:
            storage = value["storage"]
            details = value["details"]
            if not isinstance(storage, Mapping) or not isinstance(details, Mapping):
                raise TypeError("storage and details must be objects")
            return cls(
                fixture_kind=value["fixture_kind"],
                manifest_version=value["manifest_version"],
                fixture_id=value["fixture_id"],
                storage_format=storage["format"],
                storage_path=storage["path"],
                created_at=value["created_at"],
                updated_at=value["updated_at"],
                details=details,
            )
        except FixtureManifestError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise FixtureManifestError("invalid fixture manifest envelope") from exc


__all__ = [
    "FIXTURES_DIR",
    "FIXTURE_MANIFEST_NAME",
    "FIXTURE_MANIFEST_VERSION",
    "FixtureManifestEnvelope",
    "FixtureManifestError",
    "FixturePaths",
    "fixture_paths",
    "fixtures_root",
    "validate_fixture_component",
]
