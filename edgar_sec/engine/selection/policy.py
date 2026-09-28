"""Declarative selection policy: the quota profile a plan is built against.

A policy names the corpus, the target forms, the era bands, and the floors,
composites, weights, and caps that define a balanced sample. Nothing about
stratification is hardcoded in the selector: the policy is the only place a
form name, an era boundary, or a dimension weight appears, so changing the
quota profile never requires editing Python.

This module owns all date-bound reasoning. :mod:`.features` maps dates onto era
bands and :mod:`.selector` consumes the result, but neither one decides what a
date means.

Departures from v1:

* ``resolve_paths`` is imported lazily inside :func:`discover_policies` rather
  than at module scope, keeping import cost off the common path.
* ``auto_generate_policy`` reads the catalog through the same
  ``FilingCatalogPaths`` resolver the pipeline uses, instead of v1's
  ``manifests_root / "filing_extraction" / "filing_catalog"`` string
  concatenation, which had to be kept in sync with the layout by hand.
* Policy validation rejects a floor or cap naming an unknown dimension at
  construction time. v1 validated only ``floors``/``weights``/``caps`` keys
  against a partial set, so a typo inside a composite's ``filters`` was only
  discovered after the snapshot had already been built.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import (
    AMENDMENT_POLICIES,
    DEFAULT_AMENDMENT,
    DEFAULT_DOCUMENT_SUFFIXES,
    normalize_suffixes,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json

POLICY_SCHEMA_VERSION = "1.0"

# Every dimension the selector is allowed to stratify on. A policy referencing
# anything else is rejected at construction rather than silently ignored.
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

_DIGEST_LENGTH = 32


def _fingerprint(data: Any) -> str:
    return canonical_hash(data)[:_DIGEST_LENGTH]


@dataclass(frozen=True, slots=True)
class EraBand:
    """An explicit bounded year or date interval for era categorization.

    Bounds are half-open on years (``start_year`` inclusive, ``end_year``
    exclusive) and half-open on dates, which is what makes adjacent bands tile
    a range without overlapping: ``(1995, 2005)`` then ``(2005, 2011)`` covers
    every year exactly once.
    """

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
        def _optional_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if value is not None else None

        def _optional_str(key: str) -> str | None:
            value = data.get(key)
            return str(value) if value is not None else None

        return cls(
            name=str(data["name"]),
            start_year=_optional_int("start_year"),
            end_year=_optional_int("end_year"),
            start_date=_optional_str("start_date"),
            end_date=_optional_str("end_date"),
        )


@dataclass(frozen=True, slots=True)
class SeedFiler:
    """One normalized row of the seed CIK manifest.

    Seed filers are registrants that must appear in the output regardless of
    quota arithmetic -- an anchor tenant, a known-good counterparty.
    """

    cik: str
    seed_group: str = "default"
    coverage_tags: str = ""
    notes: str = ""


def load_seed_cik_csv(path: str | Path) -> dict[str, SeedFiler]:
    """Parse and validate a seed CIK CSV, normalizing every CIK to ten digits.

    A missing ``seed-cik.csv`` falls back to a sibling ``cik-sec.csv``: v1 shipped
    both names for the same file and let the policy point at either.
    """
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
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
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
    """Hash the seed set by value, not by file order.

    Sorting by CIK makes the fingerprint independent of row order in the CSV, so
    re-sorting the manifest does not invalidate every plan built from it, while
    editing any seed's group or notes does.
    """
    rows = [
        [entry.cik, entry.seed_group, entry.coverage_tags, entry.notes]
        for entry in sorted(seed_map.values(), key=lambda item: item.cik)
    ]
    return _fingerprint(rows)


@dataclass
class SelectionPolicy:
    """The declarative quota profile for one target plan.

    Mutable, and validated in ``__post_init__``: a policy is built by a human or
    a generator, so the error has to surface where the bad field is written
    rather than hours later inside a selector.
    """

    corpus_id: str
    forms: list[str]
    amendment: str = DEFAULT_AMENDMENT
    document_suffixes: list[str] = field(default_factory=list)
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
        self.forms = list(
            dict.fromkeys(
                str(form).strip().upper() for form in self.forms if str(form).strip()
            )
        )
        if not self.forms:
            raise ValueError("forms must contain at least one form string")
        if self.amendment not in AMENDMENT_POLICIES:
            raise ValueError(
                f"amendment must be one of {', '.join(AMENDMENT_POLICIES)}"
            )
        self.document_suffixes = list(
            normalize_suffixes([str(suffix) for suffix in self.document_suffixes])
        )
        if self.base_content_units < 1:
            raise ValueError("base_content_units must be positive")
        if self.level < 1:
            raise ValueError("level must be at least 1")
        if self.max_per_company_classification is not None and (
            self.max_per_company_classification < 1
        ):
            raise ValueError("max_per_company_classification must be at least 1")

        for dim, cap in self.caps.items():
            if not 0 < cap <= 1:
                raise ValueError(f"cap for {dim} must be in (0, 1]")

        # v1 checked only the top-level dimension names, so a typo inside a
        # composite's filters passed construction and then produced an
        # unmatchable stratum. Every referenced dimension is checked here.
        unknown = (
            set(self.floors)
            | set(self.weights)
            | set(self.caps)
            | set(self.value_weights)
        )
        for composite in self.composites:
            unknown |= set(composite.get("filters", {}))
        unknown -= set(KNOWN_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown policy dimensions: {sorted(unknown)}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["era_bands"] = [band.to_dict() for band in self.era_bands]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionPolicy:
        parsed = dict(data)
        if isinstance(parsed.get("era_bands"), list):
            parsed["era_bands"] = [
                EraBand.from_dict(band) if isinstance(band, dict) else band
                for band in parsed["era_bands"]
            ]
        return cls(**parsed)

    @classmethod
    def from_json(cls, payload: str) -> SelectionPolicy:
        return cls.from_dict(json.loads(payload))

    @classmethod
    def from_path(cls, path: str | Path) -> SelectionPolicy:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def write(self, path: str | Path) -> Path:
        """Persist the policy atomically, indented for hand editing.

        ``canonical=False`` keeps the dataclass's own field order rather than
        sorting keys, matching how ``write_plan_documents`` writes ``plan.json``:
        a policy document is read and edited by people, and declaration order is
        the order a person thinks about the fields in. The fingerprint is
        unaffected either way, because :func:`canonical_hash` sorts on its own.
        """
        destination = Path(path).resolve()
        atomic_write_json(destination, self.to_dict(), canonical=False, indent=2)
        return destination

    @property
    def policy_fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    def requested_units(self) -> int:
        return self.base_content_units

    def validate_dimensions(self, available: set[str]) -> None:
        """Raise if the policy stratifies on a dimension the snapshot lacks.

        Called by the selector against the snapshot it was handed, because only
        the snapshot knows which dimensions actually survived feature building.
        """
        referenced = set(self.floors) | set(self.weights) | set(self.caps)
        for composite in self.composites:
            referenced |= set(composite.get("filters", {}))
        missing = referenced - available
        if missing:
            raise ValueError(
                f"policy references dimensions absent from snapshot: {sorted(missing)}"
            )


def _era_bands_for_range(min_year: int, max_year: int) -> list[EraBand]:
    """Tile ``[min_year, max_year]`` into contiguous, non-overlapping bands.

    A short range gets one band per year. A longer one is binned so each band
    spans roughly four years, capped at six bands: more bands than that and no
    single stratum is wide enough to fill its floor.
    """
    total_years = max_year - min_year + 1
    if total_years <= 4:
        return [
            EraBand(name=str(year), start_year=year, end_year=year + 1)
            for year in range(min_year, max_year + 1)
        ]

    num_bins = min(6, max(3, round(total_years / 4)))
    bin_width = -(-total_years // num_bins)  # ceiling division
    bands: list[EraBand] = []
    current = min_year
    while current <= max_year:
        following = min(current + bin_width, max_year + 1)
        name = f"{current}_{following - 1}" if following - 1 > current else str(current)
        bands.append(EraBand(name=name, start_year=current, end_year=following))
        current = following
    return bands


def auto_generate_policy(
    catalog_id: str,
    forms: Sequence[str],
    min_year: int,
    max_year: int,
    dest: Path | None = None,
) -> SelectionPolicy:
    """Derive a baseline policy from a catalog's own forms and year range.

    The observed form list and the observed report-year range are *parameters*,
    not paths, because Layer 3 may not reach the Layer 4 catalog layout. The
    caller resolves the published snapshot and reads those two facts;
    ``pipelines.filing_catalog.discovery.generate_policy`` is that caller. v1
    concatenated ``manifests_root / "filing_extraction" / "filing_catalog"`` by
    hand inside this function, which meant a layout change had to be mirrored
    here or policy generation would silently read nothing.
    """
    if max_year < min_year:
        raise ValueError(f"catalog year range is inverted: {min_year}..{max_year}")
    normalized_forms = [
        str(form).strip().upper() for form in forms if str(form).strip()
    ]
    bands = _era_bands_for_range(min_year, max_year)
    policy = SelectionPolicy(
        corpus_id=f"corpus_{catalog_id[:8]}",
        forms=normalized_forms or ["10-K"],
        era_bands=bands,
        base_content_units=min(500, max(100, (max_year - min_year + 1) * 20)),
    )
    if dest is not None:
        policy.write(dest)
    return policy


def discover_policies(search_dirs: Sequence[str | Path]) -> list[dict[str, Any]]:
    """Summarize valid policy documents found in the given directories.

    Files that fail to parse as a policy are skipped rather than raising, so a
    directory holding unrelated JSON can be scanned; only validated policies are
    returned, which is what makes the result safe to render in an operator menu.

    ``search_dirs`` is required. The default search location is a property of the
    artifact layout, which belongs to Layer 4, so resolving it here would be an
    upward import. ``pipelines.filing_catalog.discovery.discover_policies``
    supplies it.
    """
    summaries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw_dir in search_dirs:
        directory = Path(raw_dir)
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.json")):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                policy = SelectionPolicy.from_path(resolved)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            summaries.append(
                {
                    "path": str(resolved),
                    "name": resolved.name,
                    "corpus_id": policy.corpus_id,
                    "forms": list(policy.forms),
                    "level": policy.level,
                    "base_content_units": policy.base_content_units,
                    "policy_fingerprint": policy.policy_fingerprint,
                    "seed_cik_path": policy.seed_cik_path,
                }
            )
    return summaries


def normalize_value(value: Any) -> str:
    """Normalize a dimension value for policy comparison and reporting.

    A missing value and the literal string ``"none"`` must collapse to the same
    bucket, otherwise a floor on ``"none"`` would count as unmet no matter how
    many rows genuinely lack that dimension.
    """
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


__all__ = [
    "AMENDMENT_POLICIES",
    "DEFAULT_AMENDMENT",
    "DEFAULT_DOCUMENT_SUFFIXES",
    "KNOWN_DIMENSIONS",
    "POLICY_SCHEMA_VERSION",
    "EraBand",
    "SeedFiler",
    "SelectionPolicy",
    "auto_generate_policy",
    "compute_seed_fingerprint",
    "discover_policies",
    "load_seed_cik_csv",
    "normalize_suffixes",
    "normalize_value",
]
