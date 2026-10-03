"""Declarative selection policy: the quota profile a plan is built against.

A policy names the corpus, the target forms, the era bands, the date selection,
and the floors, composites, and caps that define a balanced sample. Nothing
about stratification is hardcoded in the selector: the policy is the only place
a form name, an era boundary, or a dimension share cap appears, so changing the
quota profile never requires editing Python.

This module owns all date-bound reasoning. :mod:`.features` maps dates onto era
bands and :mod:`.selector` consumes the result, but neither one decides what a
date means.

A field that nothing reads is not configuration, it is a second, unenforced
claim about what selection does. The policy carries none: ``weights`` and
``value_weights`` were validated for dimension names and then never consulted,
because the final fill is sequential under the cap check rather than weighted;
``seed_groups`` named groups the seed CSV already labels per filer; and
``policy_schema_version`` was never branched on, so the enforced version lives
in the plan document (:data:`.publication.TARGET_PLAN_SCHEMA_VERSION`) where
expansion checks it. A retired key is rejected outright rather than ignored, so
an older draft fails to load instead of selecting something nobody intended.

Policy generation takes the catalog's forms and year range from its caller,
keeping artifact discovery in the pipeline layer. Construction validates every
referenced dimension, including composite filters, before selection begins.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import (
    DEFAULT_DOCUMENT_SUFFIXES,
    DateSelection,
    date_selection_from_json,
    date_selection_to_json,
    format_date_selection,
    normalize_suffixes,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text

# Keys a policy document used to carry that nothing reads. A draft still
# declaring one is refused rather than loaded with the key dropped, because a
# silently ignored key is exactly the unenforced claim these fields were.
_RETIRED_POLICY_FIELDS = frozenset(
    {"seed_groups", "weights", "value_weights", "policy_schema_version"}
)

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

# The two grains a dimension can be counted at, kept beside the vocabulary they
# partition rather than inside the module that happens to count. Selection draws
# candidates and composites from `locator_features`, so a composite stratum can
# only name a locator-grain dimension; counting a per-filing dimension on the
# locator table would read as an undersupplied stratum rather than a bad policy.
# `sic_code` is locator-grain: the locator projection carries the representative
# registrant's value.
OCCURRENCE_ONLY_DIMENSIONS = frozenset({"accession_class"})
LOCATOR_ONLY_DIMENSIONS = frozenset(
    name for name in KNOWN_DIMENSIONS if name not in OCCURRENCE_ONLY_DIMENSIONS
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


# The CSV header a seed sidecar is written and read with. One owner for the
# format, so the writer and the reader cannot drift.
SEED_FILER_COLUMNS = ("cik", "seed_group", "coverage_tags", "notes")


def load_seed_cik_csv(path: str | Path) -> dict[str, SeedFiler]:
    """Parse and validate a seed CIK CSV, normalizing every CIK to ten digits.

    A missing ``seed-cik.csv`` falls back to a sibling ``cik-sec.csv``.
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


def resolve_seed_filers(policy: SelectionPolicy) -> dict[str, SeedFiler]:
    """Return the seed set a policy configures, or an empty set when it has none.

    A policy pointing at a file that does not exist is a normal state, not an
    error: company-family data then falls back to the profile corpus and
    selection runs without mandatory filers. The distinction is recorded in the
    plan rather than raised, because an absent optional manifest is a different
    situation from a malformed one -- a malformed manifest still raises, from
    :func:`load_seed_cik_csv`.
    """
    path = Path(policy.seed_cik_path)
    if not path.is_absolute() and not path.is_file():
        candidate = Path.cwd() / path
        if candidate.is_file():
            path = candidate
    if not path.is_file():
        return {}
    return load_seed_cik_csv(path)


def write_seed_filers_csv(path: str | Path, seed_map: dict[str, SeedFiler]) -> None:
    """Write the normalized seed set as the plan's immutable seed sidecar.

    Sorted by CIK so the file is byte-stable for a given seed set, which is what
    lets a published plan be reproduced from its own bundle.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(SEED_FILER_COLUMNS)]
    for entry in sorted(seed_map.values(), key=lambda item: item.cik):
        lines.append(
            ",".join(
                _csv_field(value)
                for value in (
                    entry.cik,
                    entry.seed_group,
                    entry.coverage_tags,
                    entry.notes,
                )
            )
        )
    atomic_write_text(destination, "\n".join(lines) + "\n")


def read_seed_filers_csv(path: str | Path) -> dict[str, SeedFiler]:
    """Read a published seed sidecar back into a normalized seed set."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"plan seed sidecar not found: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [
            name for name in SEED_FILER_COLUMNS if name not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"seed sidecar is missing columns {missing}: {source}")
        seed_map: dict[str, SeedFiler] = {}
        for row in reader:
            cik = (row.get("cik") or "").strip()
            if not cik:
                continue
            seed_map[cik] = SeedFiler(
                cik=cik,
                seed_group=(row.get("seed_group") or "default").strip(),
                coverage_tags=(row.get("coverage_tags") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
    return seed_map


def _csv_field(value: str) -> str:
    """Quote a seed field only when it would otherwise break the row."""
    if any(character in value for character in (",", '"', "\n", "\r")):
        return '"' + value.replace('"', '""') + '"'
    return value


def compute_seed_fingerprint(seed_map: dict[str, SeedFiler]) -> str:
    """Hash the seed set by value, not by file order.

    Sorting by CIK makes the fingerprint independent of row order in the CSV, so
    re-sorting the manifest does not invalidate every plan built from it, while
    editing any seed's group, tags, or notes does.
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
    document_suffixes: list[str] = field(default_factory=list)
    date_selection: list[dict[str, Any]] = field(default_factory=list)
    era_bands: list[EraBand] = field(default_factory=list)
    seed_cik_path: str = "uploads/cik-sec.csv"
    base_content_units: int = 500
    level: int = 1
    parent_plan_id: str | None = None
    parent_plan_fingerprint: str | None = None
    floors: dict[str, dict[str, int]] = field(default_factory=dict)
    composites: list[dict[str, Any]] = field(default_factory=list)
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
        self.document_suffixes = list(
            normalize_suffixes([str(suffix) for suffix in self.document_suffixes])
        )
        # The declared form is re-canonicalized rather than stored as written, so
        # the fingerprint of an unchanged policy does not depend on how a human
        # ordered or re-spelled its clauses. A policy document is hand-edited,
        # so "these two files mean the same thing" has to hold.
        self.date_selection = date_selection_to_json(
            date_selection_from_json(self.date_selection)
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

        # Validate nested composite filters before selection queries run.
        unknown = set(self.floors) | set(self.caps)
        for composite in self.composites:
            unknown |= set(composite.get("filters", {}))
        unknown -= set(KNOWN_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown policy dimensions: {sorted(unknown)}")

        # A composite is selected from the locator table, so a stratum filtered
        # on a dimension that only exists per filing can never be matched. The
        # vocabulary check above cannot tell grains apart, so without this the
        # failure surfaces as a DuckDB Binder Error from deep inside selection,
        # naming a column rather than the policy field that caused it. Refusing
        # it here names both.
        occurrence_only = sorted(
            {
                dimension
                for composite in self.composites
                for dimension in composite.get("filters", {})
                if dimension in OCCURRENCE_ONLY_DIMENSIONS
            }
        )
        if occurrence_only:
            raise ValueError(
                "composite strata select from locator_features, which has no "
                f"column for {occurrence_only}; use a locator-grain dimension"
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["era_bands"] = [band.to_dict() for band in self.era_bands]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectionPolicy:
        parsed = dict(data)
        retired = sorted(set(parsed) & _RETIRED_POLICY_FIELDS)
        if retired:
            raise ValueError(
                f"policy declares retired keys {retired}, which nothing reads; "
                f"delete them and republish the draft. A key selection ignores "
                f"is a second, unenforced claim about what the plan selects."
            )
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

    @property
    def date_selection_clauses(self) -> DateSelection:
        """The declared selection as typed clauses, ready to compile to SQL.

        Decoding from the stored form on each access keeps one representation:
        the policy document holds JSON, so a fingerprint and a predicate cannot
        be taken from two different normalizations of the same clauses.
        """
        return date_selection_from_json(self.date_selection)

    @property
    def date_selection_text(self) -> str:
        """The selection in the ``--dates`` grammar, for reports and prompts."""
        return format_date_selection(self.date_selection_clauses)

    @property
    def derives_era_bands(self) -> bool:
        """Whether era bands are derived from the catalog rather than declared.

        An empty list means auto, not "no strata": a policy with no bands would
        sample across all years at once, which is the one thing era banding
        exists to prevent. The planner resolves the bands from the years the
        catalog actually holds -- after the declared forms and date selection --
        and writes the resolved bands into the published plan.
        """
        return not self.era_bands

    def with_era_bands(self, bands: Sequence[EraBand]) -> SelectionPolicy:
        """Return a copy carrying explicit bands, for embedding in a plan.

        The plan must record the bands selection actually used. Auto bands are
        derived from data that can change, so re-deriving them on a later read
        of the plan could produce a different stratification than the one the
        published locators were chosen under.
        """
        if not bands:
            raise ValueError("resolved era bands must not be empty")
        clone = replace(self, era_bands=list(bands))
        return clone

    def requested_units(self) -> int:
        return self.base_content_units

    def validate_dimensions(self, available: set[str]) -> None:
        """Raise if the policy stratifies on a dimension the snapshot lacks.

        Called by the selector against the snapshot it was handed, because only
        the snapshot knows which dimensions actually survived feature building.
        """
        referenced = set(self.floors) | set(self.caps)
        for composite in self.composites:
            referenced |= set(composite.get("filters", {}))
        missing = referenced - available
        if missing:
            raise ValueError(
                f"policy references dimensions absent from snapshot: {sorted(missing)}"
            )


def era_bands_for_range(min_year: int, max_year: int) -> list[EraBand]:
    """Tile ``[min_year, max_year]`` into contiguous, non-overlapping bands.

    A short range gets one band per year. A longer one is binned so each band
    spans roughly four years, capped at six bands: more bands than that and no
    single stratum is wide enough to fill its floor.

    This is the automatic mode. A policy that declares its own bands never
    reaches it, and the bands a published plan records are the ones its selection
    actually used.
    """
    if max_year < min_year:
        raise ValueError(f"year range is inverted: {min_year}..{max_year}")
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

    The caller supplies observed forms and the report-year range so this engine
    module does not discover Layer 4 artifact paths. The pipeline resolves the
    published catalog and passes those values here.
    """
    if max_year < min_year:
        raise ValueError(f"catalog year range is inverted: {min_year}..{max_year}")
    normalized_forms = [
        str(form).strip().upper() for form in forms if str(form).strip()
    ]
    bands = era_bands_for_range(min_year, max_year)
    policy = SelectionPolicy(
        corpus_id=f"corpus_{catalog_id[:8]}",
        forms=normalized_forms,
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
                    # Enough to tell two drafts apart in a menu without reading
                    # either: the fields that change what a plan selects.
                    "date_selection_text": policy.date_selection_text,
                    "derives_era_bands": policy.derives_era_bands,
                    "era_band_count": len(policy.era_bands),
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
    "DEFAULT_DOCUMENT_SUFFIXES",
    "KNOWN_DIMENSIONS",
    "SEED_FILER_COLUMNS",
    "EraBand",
    "SeedFiler",
    "SelectionPolicy",
    "auto_generate_policy",
    "compute_seed_fingerprint",
    "discover_policies",
    "era_bands_for_range",
    "load_seed_cik_csv",
    "normalize_suffixes",
    "normalize_value",
    "read_seed_filers_csv",
    "resolve_seed_filers",
    "write_seed_filers_csv",
]
