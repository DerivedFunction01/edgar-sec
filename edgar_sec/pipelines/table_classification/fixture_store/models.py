"""Typed records and errors for classification product fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.hashing import is_prefixed_hex_id

STORE_VERSION = 1
FIXTURE_KIND = "table_classification_products"
DATASET = "table_classification"


class FixtureStoreError(RuntimeError):
    """A fixture is missing, corrupt, or stale for its stamps."""


class FixtureOperationError(ValueError):
    """A fixture operation was requested with invalid inputs."""


@dataclass(frozen=True, slots=True)
class ProductStamps:
    """Versions a fixture's computed products are valid for, exactly."""

    normalize_version: str
    renderer_version: str
    page_policy: str

    def __post_init__(self) -> None:
        if not self.normalize_version or not self.renderer_version:
            raise ValueError("product stamps require normalize/renderer versions")
        if not self.page_policy:
            raise ValueError("product stamps require a page policy")

    def as_record(self) -> dict[str, str]:
        """The manifest form of the stamps."""
        return {
            "normalize_version": self.normalize_version,
            "renderer_version": self.renderer_version,
            "page_policy": self.page_policy,
        }

    @classmethod
    def from_record(cls, record: dict) -> ProductStamps:
        """Rebuild stamps from their manifest form."""
        return cls(
            normalize_version=str(record["normalize_version"]),
            renderer_version=str(record["renderer_version"]),
            page_policy=str(record["page_policy"]),
        )


@dataclass(frozen=True, slots=True)
class PlanPin:
    """The plan a fixture was captured against, in header vocabulary.

    Field names mirror the core provenance header (contract v1):
    plan_format_version, plan_id, registry_state, source_snapshot_id.
    """

    plan_format_version: str
    plan_id: str
    registry_state: str
    source_snapshot_id: str

    def __post_init__(self) -> None:
        if (
            not self.plan_format_version
            or not is_prefixed_hex_id(self.plan_id, "tcplan-", 16)
            or not is_prefixed_hex_id(self.registry_state, "sha256:", 64)
            or not self.source_snapshot_id
        ):
            raise ValueError("fixture plan pin is invalid")

    def as_record(self) -> dict:
        """The manifest form of the pin."""
        return {
            "plan_format_version": self.plan_format_version,
            "plan_id": self.plan_id,
            "registry_state": self.registry_state,
            "source_snapshot_id": self.source_snapshot_id,
        }

    @classmethod
    def from_record(cls, record: dict) -> PlanPin:
        """Rebuild a pin from its manifest form."""
        return cls(
            plan_format_version=str(record["plan_format_version"]),
            plan_id=str(record["plan_id"]),
            registry_state=str(record["registry_state"]),
            source_snapshot_id=str(record["source_snapshot_id"]),
        )


@dataclass(frozen=True, slots=True)
class FixtureCaseKey:
    """One captured document inside a fixture."""

    accession: str
    source_document: str

    @property
    def case_id(self) -> str:
        """The stable on-disk case identifier."""
        return f"{self.accession}--{self.source_document}"


@dataclass(frozen=True, slots=True)
class CapturedCase:
    """One case entering capture: its key, stamps, and products."""

    key: FixtureCaseKey
    stamps: ProductStamps
    products: dict


@dataclass(frozen=True, slots=True)
class FixtureCaseMetadata:
    """One stored case, without its products loaded."""

    fixture_id: str
    key: FixtureCaseKey
    stamps: ProductStamps
    products_sha256: str


@dataclass(frozen=True, slots=True)
class FixtureSummary:
    """One discovered fixture's manifest-level facts."""

    fixture_id: str
    plan_pin: PlanPin
    stamps: ProductStamps
    case_count: int


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """What one capture call stored or reused."""

    fixture_id: str
    cases_added: int
    cases_reused: int
