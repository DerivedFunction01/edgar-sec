"""The declarative quota profile a plan is built against, and the only place a form
name, an era boundary, or a dimension cap appears. Owns all date-bound reasoning:
features maps dates onto era bands and selector consumes the result.
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

# Every dimension the selector may stratify on; anything else is rejected at
# construction rather than silently ignored.
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
    "locator_class",
    "stub_suspect",
    "company_family",
)

_DIGEST_LENGTH = 32


def _fingerprint(data: Any) -> str:
    return canonical_hash(data)[:_DIGEST_LENGTH]


@dataclass(frozen=True, slots=True)
class EraBand:
    """A bounded year or date interval for era categorization. Half-open (`start`
    inclusive, `end` exclusive) so adjacent bands tile a range without overlapping.
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
    """One normalized row of the seed CIK manifest: a registrant that must appear
    in the output regardless of quota arithmetic.
    """

    cik: str
    seed_group: str = "default"
    coverage_tags: str = ""
    notes: str = ""


# One owner for the seed CSV format, so writer and reader cannot drift.
SEED_FILER_COLUMNS = ("cik", "seed_group", "coverage_tags", "notes")


def load_seed_cik_csv(path: str | Path) -> dict[str, SeedFiler]:
    """Parse and validate a seed CIK CSV, normalizing every CIK to ten digits; a
    missing ``seed-cik.csv`` falls back to a sibling ``cik-sec.csv``.
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
    """The seed set a policy configures, or empty when it configures none. An absent
    optional manifest is a normal state; a malformed one still raises.
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
    """Write the seed set as the plan's immutable seed sidecar, sorted by CIK so the
    file is byte-stable and a published plan is reproducible from its own bundle.
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
    """Hash the seed set by value, not by file order: re-sorting the manifest must not
    invalidate every plan built from it, while editing a seed's group or notes must.
    """
    rows = [
        [entry.cik, entry.seed_group, entry.coverage_tags, entry.notes]
        for entry in sorted(seed_map.values(), key=lambda item: item.cik)
    ]
    return _fingerprint(rows)


@dataclass
class SelectionPolicy:
    """The declarative quota profile for one target plan, validated in `__post_init__`
    so a bad field surfaces where it is written, not hours later in a selector.
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
        # Re-canonicalized rather than stored as written, so an unchanged policy's
        # fingerprint cannot depend on how a human ordered or re-spelled it.
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
        """Persist the policy atomically, in declaration order for hand editing; the
        fingerprint is unaffected either way because canonical_hash sorts on its own.
        """
        destination = Path(path).resolve()
        atomic_write_json(destination, self.to_dict(), canonical=False, indent=2)
        return destination

    @property
    def policy_fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    @property
    def date_selection_clauses(self) -> DateSelection:
        """The declared selection as typed clauses, decoded on each access so a
        fingerprint and a predicate cannot disagree on the normalization.
        """
        return date_selection_from_json(self.date_selection)

    @property
    def date_selection_text(self) -> str:
        """The selection in the ``--dates`` grammar, for reports and prompts."""
        return format_date_selection(self.date_selection_clauses)

    @property
    def derives_era_bands(self) -> bool:
        """Whether era bands are derived from the catalog. Empty means auto, not "no
        strata": banding exists to stop sampling every year at once.
        """
        return not self.era_bands

    def with_era_bands(self, bands: Sequence[EraBand]) -> SelectionPolicy:
        """A copy carrying explicit bands, for embedding in a plan: re-deriving them on a
        later read could stratify differently from the published locators.
        """
        if not bands:
            raise ValueError("resolved era bands must not be empty")
        clone = replace(self, era_bands=list(bands))
        return clone

    def requested_units(self) -> int:
        return self.base_content_units

    def validate_dimensions(self, available: set[str]) -> None:
        """Raise if the policy stratifies on a dimension the snapshot lacks: only the
        snapshot knows which dimensions survived feature building.
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
    """Tile `[min_year, max_year]` into contiguous bands: one per year for a short
    range, otherwise ~4-year bands capped at six, below which floors cannot fill.
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
    """Derive a baseline policy from a catalog's own forms and year range; the caller
    supplies both, keeping artifact discovery in Layer 4.
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
    """Summarize valid policy documents in the given directories; unparseable files are
    skipped so unrelated JSON stays scannable. `search_dirs` is required.
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
                    # Fields that change what a plan selects: enough to
                    # tell two drafts apart in a menu.
                    "date_selection_text": policy.date_selection_text,
                    "derives_era_bands": policy.derives_era_bands,
                    "era_band_count": len(policy.era_bands),
                }
            )
    return summaries


def normalize_value(value: Any) -> str:
    """Normalize a dimension value; a missing value and the literal "none" must
    collapse together, or a floor on "none" could never be met.
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
