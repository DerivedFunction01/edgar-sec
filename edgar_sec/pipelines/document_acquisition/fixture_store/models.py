"""Typed results and errors for parser-body fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.hashing import is_sha256_hex_digest


class FixtureStoreError(RuntimeError):
    """A fixture is missing, corrupt, incompatible, or conflicts with immutable evidence."""


class FixtureOperationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FixtureBodyRef:
    body_sha256: str
    byte_size: int
    stored_sha256: str
    stored_byte_size: int
    reused: bool


@dataclass(frozen=True, slots=True)
class FixturePlanPin:
    target_plan_id: str
    target_plan_digest: str
    target_plan_schema_version: int

    def __post_init__(self) -> None:
        if (
            not self.target_plan_id
            or not is_sha256_hex_digest(self.target_plan_digest)
            or type(self.target_plan_schema_version) is not int
            or self.target_plan_schema_version < 1
        ):
            raise ValueError("fixture plan pin is invalid")


@dataclass(frozen=True, slots=True)
class FixturePlanCaptureResult:
    fixture_id: str
    capture_id: str | None
    captured_cases: int
    skipped_targets: int
    failed_targets: int
    fetched_lazy_indexes: int
    reused_lazy_indexes: int
    failure_counts: dict[str, int]
