"""Declarative policy model and seed parsing for Phase 02 target selection.

Policies define corpus identity, target forms, explicit era bands, floors,
composites, weights, caps, and seed file references without hardcoding any form
or domain defaults into Python code.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from defs.storage import atomic_write_json, canonical_json, load_json

POLICY_SCHEMA_VERSION = "1.0"

KNOWN_DIMENSIONS = (
    "form",
    "form_family",
    "era",
    "suffix",
    "xbrl_state",
    "size_band",
    "sic_code",
    "owner_org_presence",
    "foreign_status",
    "foreign_country_code",
    "entity_type",
    "filer_category_primary",
    "lifecycle_class",
    "has_revival_gap",
    "accession_class",
    "locator_class",
    "stub_suspect",
    "anchor_status",
    "comparison_status",
    "company_name",
    "company_family",
)


def _sha256_of_data(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EraBand:
    """Explicit bounded date/year interval for policy-driven era categorization."""

    name: str
    start_year: int | None = None
    end_year: int | None = None
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("era band name must be a non-empty string")
        if (
            self.start_year is None
            and self.end_year is None
            and self.start_date is None
            and self.end_date is None
        ):
            raise ValueError(
                f"era band {self.name!r} must specify at least one boundary"
            )

    def matches(self, year: int | None, date_str: str | None) -> bool:
        if self.start_year is not None and (year is None or year < self.start_year):
            return False
        if self.end_year is not None and (year is None or year >= self.end_year):
            return False
        if self.start_date is not None and (
            date_str is None or date_str < self.start_date
        ):
            return False
        return not (
            self.end_date is not None
            and (date_str is None or date_str >= self.end_date)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EraBand:
        return cls(
            name=str(data["name"]),
            start_year=int(data["start_year"])
            if data.get("start_year") is not None
            else None,
            end_year=int(data["end_year"])
            if data.get("end_year") is not None
            else None,
            start_date=str(data["start_date"])
            if data.get("start_date") is not None
            else None,
            end_date=str(data["end_date"])
            if data.get("end_date") is not None
            else None,
        )


@dataclass(frozen=True)
class SeedFiler:
    """Normalized entry from uploads/seed-cik.csv."""

    cik: str
    seed_group: str = "default"
    coverage_tags: str = ""
    notes: str = ""


def load_seed_cik_csv(path: str | Path) -> dict[str, SeedFiler]:
    """Parse and validate seed CIK CSV file with 10-digit zero-padding."""
    source_path = Path(path).resolve()
    if not source_path.is_file():
        if (
            source_path.name == "seed-cik.csv"
            and (source_path.parent / "cik-sec.csv").is_file()
        ):
            source_path = source_path.parent / "cik-sec.csv"
        else:
            raise FileNotFoundError(f"seed CIK file not found: {source_path}")

    seed_map: dict[str, SeedFiler] = {}
    with source_path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "cik" not in reader.fieldnames:
            raise ValueError(f"seed CSV missing required 'cik' column: {source_path}")

        for line_no, row in enumerate(reader, start=2):
            raw_cik = (row.get("cik") or "").strip()
            if not raw_cik:
                continue
            digits = "".join(ch for ch in raw_cik if ch.isdigit())
            if not digits:
                raise ValueError(
                    f"invalid non-numeric CIK at line {line_no}: {raw_cik!r}"
                )
            normalized_cik = f"{int(digits):010d}"
            if normalized_cik in seed_map:
                raise ValueError(f"duplicate CIK {normalized_cik} at line {line_no}")

            seed_map[normalized_cik] = SeedFiler(
                cik=normalized_cik,
                seed_group=(row.get("seed_group") or "default").strip(),
                coverage_tags=(row.get("coverage_tags") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
    return seed_map


def compute_seed_fingerprint(seed_map: dict[str, SeedFiler]) -> str:
    """Deterministic hash of sorted seed entries."""
    rows = [
        [s.cik, s.seed_group, s.coverage_tags, s.notes]
        for s in sorted(seed_map.values(), key=lambda x: x.cik)
    ]
    return _sha256_of_data(rows)[:32]


@dataclass
class SelectionPolicy:
    """Declarative selection policy for deficit-based fixture target planning."""

    corpus_id: str
    forms: list[str]
    policy_schema_version: str = POLICY_SCHEMA_VERSION
    era_bands: list[EraBand] = field(default_factory=list)
    seed_cik_path: str = "uploads/cik-sec.csv"
    seed_groups: list[str] = field(default_factory=list)
    base_content_units: int = 500
    level: int = 1
    parent_plan_id: str | None = None
    parent_plan_fingerprint: str | None = None
    floors: dict[str, dict[str, int]] = field(default_factory=dict)
    composites: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    value_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    caps: dict[str, float] = field(default_factory=dict)
    reserve_size: int = 100
    seed: str = "fixture-selection-v1"
    max_reported_size: int | None = None
    exclude_amendments: bool = False
    anchor_forms: list[str] = field(default_factory=list)
    comparison_forms: list[str] = field(default_factory=list)
    max_per_company_classification: int = 1
    pool_per_value: int = 60
    max_pool_rounds: int = 20
    page_size: int = 5_000
    max_pages: int = 400

    def __post_init__(self) -> None:
        if not self.corpus_id or not isinstance(self.corpus_id, str):
            raise ValueError("corpus_id must be a non-empty string")
        if not self.forms or not isinstance(self.forms, list):
            raise ValueError("forms must be a non-empty list of form strings")
        if self.base_content_units < 1:
            raise ValueError("base_content_units must be positive")
        if self.level < 1:
            raise ValueError("level must be at least 1")

        unknown = (
            set(self.floors)
            | set(self.weights)
            | set(self.caps)
            | set(self.value_weights)
        ) - set(KNOWN_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown policy dimensions: {sorted(unknown)}")

        for dim, cap in self.caps.items():
            if not 0 < cap <= 1:
                raise ValueError(f"cap for {dim} must be in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["era_bands"] = [b.to_dict() for b in self.era_bands]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionPolicy:
        parsed = dict(data)
        if "era_bands" in parsed and isinstance(parsed["era_bands"], list):
            parsed["era_bands"] = [
                EraBand.from_dict(b) if isinstance(b, dict) else b
                for b in parsed["era_bands"]
            ]
        return cls(**parsed)

    @classmethod
    def from_json(cls, payload: str) -> SelectionPolicy:
        return cls.from_dict(json.loads(payload))

    @classmethod
    def from_path(cls, path: str | Path) -> SelectionPolicy:
        return cls.from_dict(load_json(path))

    def write(self, path: str | Path) -> Path:
        destination = Path(path).resolve()
        atomic_write_json(destination, self.to_dict(), indent=2, sort_keys=True)
        return destination

    @property
    def policy_fingerprint(self) -> str:
        return _sha256_of_data(self.to_dict())[:32]

    def requested_units(self) -> int:
        return self.base_content_units

    def validate_dimensions(self, available: set[str]) -> None:
        referenced = set(self.floors) | set(self.weights) | set(self.caps)
        for composite in self.composites:
            referenced |= set(composite.get("filters", {}))
        missing = referenced - available
        if missing:
            raise ValueError(
                f"policy references dimensions absent from snapshot: {sorted(missing)}"
            )


def auto_generate_policy(
    catalog_id: str,
    manifests_root: str | Path | None = None,
    dest: Path | None = None,
) -> SelectionPolicy:
    """Generate a dynamic baseline selection policy from catalog year boundaries."""
    import datetime
    from math import ceil

    from defs.runtime.paths import resolve_paths
    from defs.storage import FinalizedArtifact

    resolved = (
        resolve_paths("filing_extraction")
        if manifests_root is None
        else resolve_paths(
            "filing_extraction",
            env={"ARTIFACTS_ROOT": str(Path(manifests_root).parent)},
        )
    )
    target_dir = resolved.project.dataset_manifests(
        "filing_extraction", "filing_targets"
    )

    target_files = sorted(target_dir.glob("form=*/data.parquet"))
    target_pattern = str(target_dir / "form=*" / "data.parquet")
    current_year = datetime.datetime.now(datetime.UTC).year
    forms = [p.parent.name.split("=", 1)[1].replace("_", "/") for p in target_files]
    if not target_files:
        forms = []
        min_year, max_year = current_year - 10, current_year
    else:
        with FinalizedArtifact(target_files[0]) as artifact:
            row = artifact.run(f"""
                SELECT
                    MIN(CAST(substring(report_date, 1, 4) AS INTEGER)),
                    MAX(CAST(substring(report_date, 1, 4) AS INTEGER))
                FROM read_parquet('{target_pattern}')
                WHERE report_date IS NOT NULL
                  AND length(report_date) >= 4
                  AND CAST(substring(report_date, 1, 4) AS INTEGER) >= 1990
                  AND CAST(substring(report_date, 1, 4) AS INTEGER) <= {current_year}
            """)
            min_year = row[0][0] if row and row[0][0] else current_year - 10
            max_year = row[0][1] if row and row[0][1] else current_year

    total_years = max_year - min_year + 1
    if total_years <= 4:
        bands = [
            EraBand(name=str(y), start_year=y, end_year=y + 1)
            for y in range(min_year, max_year + 1)
        ]
    else:
        num_bins = min(6, max(3, round(total_years / 4)))
        bin_width = ceil(total_years / num_bins)
        bands = []
        curr = min_year
        while curr <= max_year:
            nxt = min(curr + bin_width, max_year + 1)
            name = f"{curr}_{nxt - 1}" if nxt - 1 > curr else str(curr)
            bands.append(EraBand(name=name, start_year=curr, end_year=nxt))
            curr = nxt

    policy = SelectionPolicy(
        corpus_id=f"corpus_{catalog_id[:8]}",
        forms=forms,
        era_bands=bands,
        seed_cik_path="uploads/cik-sec.csv",
        base_content_units=min(500, max(100, total_years * 20)),
    )
    if dest is not None:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        policy.write(dest)
    return policy


def normalize_value(value: Any) -> str:
    """Normalize a dimension value for policy comparisons and reports."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


__all__ = [
    "KNOWN_DIMENSIONS",
    "POLICY_SCHEMA_VERSION",
    "EraBand",
    "SeedFiler",
    "SelectionPolicy",
    "auto_generate_policy",
    "compute_seed_fingerprint",
    "load_seed_cik_csv",
    "normalize_value",
]
