"""Build the content-addressed feature snapshot quota selection reads. Form-family
SQL comes from the same suffix vocabulary as the Python helper, and a snapshot is
reused only while its input fingerprint matches.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
    TARGET_COLUMNS,
)
from edgar_sec.domain.forms.common.aliases import FORM_FAMILY_SUFFIXES
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.foundation.runtime.paths import PARQUET_PART_GLOB, SNAPSHOTS_DIR
from edgar_sec.engine.selection.paths import (
    FEATURE_MANIFEST_FILE,
    LIFECYCLE_FILE,
    LOCATOR_FEATURES_FILE,
    OCCURRENCE_BASE_FILE,
    OCCURRENCE_FEATURES_FILE,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE

FEATURE_SCHEMA_VERSION = "1.0"

UNMATCHED_ERA = "unknown"

# Every target column except the one projected separately as `source_projection`.
# Derived from the domain schema, so a new target column flows through without a
# second list to update.
IDENTITY_COLUMNS = ", ".join(
    column for column in TARGET_COLUMNS if column != "document_path_source"
)

# The occurrence columns `occurrence_base` settles on its own, cut from the published
# tuple so the two cannot drift. Projecting a name list from it is what stops an
# earlier stage's dropped column riding through on `o.*`.
_OCCURRENCE_JOINED_COLUMNS = ("has_revival_gap", "lifecycle_class")
OCCURRENCE_BASE_COLUMNS: tuple[str, ...] = tuple(
    column
    for column in OCCURRENCE_FEATURE_COLUMNS
    if column not in _OCCURRENCE_JOINED_COLUMNS
)

# A co-filed document's representative registrant is named in the published locator
# schema but is the occurrence row's own `source_cik`/`accession`.
_LOCATOR_SOURCE_ALIASES = {
    "representative_cik": "source_cik",
    "representative_accession": "accession",
}

_LOCATOR_CLASS_CASE = (
    "CASE WHEN loc_occ_count = 1 THEN 'single' "
    "WHEN loc_occ_count BETWEEN 2 AND 3 THEN 'low_2_to_3' "
    "ELSE 'high_4_plus' END"
)


def _locator_column_expression(column: str) -> str:
    """The published locator expression for one declared column.

    Emitting per declared name, rather than appending the computed columns, keeps the
    written file in the order `LOCATOR_FEATURE_COLUMNS` declares.
    """
    if column in _LOCATOR_SOURCE_ALIASES:
        return f"{_LOCATOR_SOURCE_ALIASES[column]} AS {column}"
    if column == "locator_class":
        return f"{_LOCATOR_CLASS_CASE} AS {column}"
    return column


DEFAULT_GAP_YEARS = 3
DEFAULT_CESSATION_GRACE_YEARS = 5
DEFAULT_STUB_SIZE_THRESHOLD = 100_000

SIZE_BAND_MULTIPLIERS = (0.25, 1.0, 4.0, 16.0)
SIZE_BAND_NAMES = ("very_small", "small", "median", "large", "very_large")
UNKNOWN_SIZE_BAND = "unknown"
UNKNOWN_FOREIGN_STATUS = "unknown"

_SQL_COLUMN_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# Named rather than inlined so a published plan can name what it excluded.
FEATURE_MANIFEST_FILE  # noqa: F401 — re-exported from paths for plan consumers
OCCURRENCE_FEATURES_FILE  # noqa: F401 — re-exported from paths for plan consumers
LOCATOR_FEATURES_FILE  # noqa: F401 — re-exported from paths for plan consumers


def form_family(form: str) -> str:
    """Collapse amendment and submission suffixes to a base family; `10-K/A` and
    `10-K_A` both become `10-K`, and an all-suffix form returns the original.
    """
    base = form.upper().strip()
    for suffix in FORM_FAMILY_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form


def form_family_sql(column: str) -> str:
    """A SQL expression equivalent to `form_family`, from the same suffix vocabulary:
    each `removesuffix` becomes one `$`-anchored `regexp_replace`, in order.
    """
    if not _SQL_COLUMN_IDENTIFIER_RE.fullmatch(column):
        raise ValueError(f"unsafe SQL column identifier: {column!r}")

    expression = f"upper(trim({column}))"
    for suffix in FORM_FAMILY_SUFFIXES:
        pattern = re.escape(suffix) + "$"
        expression = f"regexp_replace({expression}, {sql_literal(pattern)}, '')"
    collapsed = f"trim('_-' FROM {expression})"
    return f"CASE WHEN {collapsed} = '' THEN {column} ELSE {collapsed} END"


def era_of(report_date: str | None, era_bands: Sequence[EraBand]) -> str:
    """Map a report date onto the first matching policy era band; an absent or unusable
    date is `unknown`, not an error, which keeps the filing visible.
    """
    if not report_date:
        return UNMATCHED_ERA
    year = (
        int(report_date[:4])
        if len(report_date) >= 4 and report_date[:4].isdigit()
        else None
    )
    for band in era_bands:
        if band.matches(year=year, date_str=report_date):
            return band.name
    return UNMATCHED_ERA


@dataclass(frozen=True, slots=True)
class SnapshotPaths:
    snapshot_dir: Path
    manifest: Path
    occurrence_features: Path
    locator_features: Path


def _build_options(
    gap_years: int, cessation_grace_years: int, stub_size_threshold: int
) -> dict[str, int]:
    return {
        "gap_years": gap_years,
        "cessation_grace_years": cessation_grace_years,
        "stub_size_threshold": stub_size_threshold,
    }


class FeatureSnapshotBuilder:
    """Build, or reuse, the immutable feature snapshot for a policy's forms."""

    def __init__(
        self,
        target_root: str | Path,
        profile_path: str | Path,
        output_root: str | Path,
        policy: SelectionPolicy,
        *,
        family_index_path: str | Path | None = None,
        family_index_id: str = "",
        row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
        gap_years: int = DEFAULT_GAP_YEARS,
        cessation_grace_years: int = DEFAULT_CESSATION_GRACE_YEARS,
        stub_size_threshold: int = DEFAULT_STUB_SIZE_THRESHOLD,
    ) -> None:
        if gap_years < 2:
            raise ValueError("gap_years must be at least 2")
        if cessation_grace_years < 1:
            raise ValueError("cessation_grace_years must be at least 1")
        if stub_size_threshold < 1:
            raise ValueError("stub_size_threshold must be at least 1")

        self.target_root = Path(target_root).resolve()
        self.profile_path = Path(profile_path).resolve()
        self.output_root = Path(output_root).resolve()
        self.policy = policy
        self.family_index_path = (
            Path(family_index_path).resolve() if family_index_path else None
        )
        self.family_index_id = family_index_id
        self.row_group_size = row_group_size
        self.options = _build_options(
            gap_years, cessation_grace_years, stub_size_threshold
        )

    def _family_relation_sql(self) -> str:
        """A relation over the published assignment, or an empty one when absent.

        Empty keeps the column a string rather than collapsing unmatched registrants
        into one null bucket.
        """
        if self.family_index_path is None or not self.family_index_path.is_file():
            return (
                "(SELECT CAST(NULL AS VARCHAR) AS cik, "
                "CAST(NULL AS VARCHAR) AS company_family WHERE false)"
            )
        return (
            "(SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik, company_family FROM "
            f"read_parquet({sql_literal(str(self.family_index_path))}))"
        )

    # ------------------------------------------------------------- identity

    def snapshot_dir(self, forms: Sequence[str]) -> Path:
        """Return the content-addressed directory for this exact input set."""
        # No derivation-revision term: a change to how a column is derived needs
        # the snapshot directory pruned, since identical inputs resolve here.
        payload = {
            "target_root": str(self.target_root),
            "profile_path": str(self.profile_path),
            "forms": sorted(forms),
            "options": self.options,
            "policy_fingerprint": self.policy.policy_fingerprint,
            "family_index_id": self.family_index_id,
        }
        return self.output_root / SNAPSHOTS_DIR / canonical_hash(payload)[:32]

    def paths_for(self, snapshot_dir: Path) -> SnapshotPaths:
        return SnapshotPaths(
            snapshot_dir=snapshot_dir,
            manifest=snapshot_dir / FEATURE_MANIFEST_FILE,
            occurrence_features=snapshot_dir / OCCURRENCE_FEATURES_FILE,
            locator_features=snapshot_dir / LOCATOR_FEATURES_FILE,
        )

    def _is_reusable(self, manifest: Path) -> bool:
        """Whether a built snapshot's manifest describes files this build still stands behind.

        The directory name already covers every hashed input, so the only way a manifest
        can disagree with the code is a feature schema that moved without a version bump.
        """
        if not manifest.is_file():
            return False
        try:
            recorded = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return recorded.get("feature_schema_version") == FEATURE_SCHEMA_VERSION

    # ----------------------------------------------------------------- SQL

    def _target_part_files(self) -> list[Path]:
        parts = sorted(self.target_root.glob(PARQUET_PART_GLOB))
        if not parts:
            raise FileNotFoundError(f"no target part files found in {self.target_root}")
        return parts

    def _target_union(
        self, forms: Sequence[str], parts: Sequence[Path] | None = None
    ) -> str:
        """Return a relation over every target row matching the policy forms."""
        file_list = ", ".join(
            sql_literal(str(path)) for path in (parts or self._target_part_files())
        )
        quoted_forms = ", ".join(sql_literal(form) for form in sorted(forms))
        return (
            f"SELECT form, form AS catalog_form, {IDENTITY_COLUMNS}, "
            f"document_path_source FROM read_parquet([{file_list}]) "
            f"WHERE form IN ({quoted_forms})"
        )

    def _size_band_anchor_sql(self, union_sql: str) -> str:
        """A relation of (form_family, median_size); keyed on family so amendment variants
        pool, and deliberately without era, which is already a stratum.
        """
        family_expr = form_family_sql("form")
        return f"""
            SELECT {family_expr} AS form_family,
                   median(reported_size) AS median_size
            FROM ({union_sql})
            WHERE reported_size IS NOT NULL
            GROUP BY form_family
        """

    def _size_band_sql(self, size_column: str, anchor_column: str) -> str:
        """Band a size against its own family's median; row-local once the anchor exists,
        so it folds into the occurrence base projection rather than a join back.
        """
        cases = [
            f"WHEN {size_column} < {anchor_column} * {multiplier} "
            f"THEN {sql_literal(name)}"
            for name, multiplier in zip(
                SIZE_BAND_NAMES[:-1], SIZE_BAND_MULTIPLIERS, strict=True
            )
        ]
        return (
            f"CASE WHEN {size_column} IS NULL OR {anchor_column} IS NULL "
            f"THEN {sql_literal(UNKNOWN_SIZE_BAND)} "
            f"{' '.join(cases)} ELSE {sql_literal(SIZE_BAND_NAMES[-1])} END"
        )

    def _era_sql(self, column: str) -> str:
        cases: list[str] = []
        for band in self.policy.era_bands:
            conditions: list[str] = []
            if band.start_year is not None:
                conditions.append(
                    f"CAST(substring({column}, 1, 4) AS INTEGER) >= {band.start_year}"
                )
            if band.end_year is not None:
                conditions.append(
                    f"CAST(substring({column}, 1, 4) AS INTEGER) < {band.end_year}"
                )
            if band.start_date is not None:
                conditions.append(f"{column} >= {sql_literal(band.start_date)}")
            if band.end_date is not None:
                conditions.append(f"{column} <= {sql_literal(band.end_date)}")
            if conditions:
                cases.append(
                    f"WHEN {' AND '.join(conditions)} THEN {sql_literal(band.name)}"
                )
        if not cases:
            return sql_literal(UNMATCHED_ERA)
        return (
            f"CASE WHEN {column} IS NULL OR length({column}) < 4 "
            f"THEN {sql_literal(UNMATCHED_ERA)} {' '.join(cases)} "
            f"ELSE {sql_literal(UNMATCHED_ERA)} END"
        )

    def _profiles_sql(self) -> str:
        """Project the nested profile schema onto the flat feature shape; blanks normalize
        to NULL in `raw`, and a missing state is `unknown`, never `domestic`.
        """
        domestic = ", ".join(sql_literal(code) for code in sorted(STATE_POSTAL_CODES))
        return f"""
            WITH raw AS (
                SELECT
                    cik,
                    NULLIF(trim(classification.sic_code), '') AS sic_code,
                    NULLIF(trim(incorporation.state), '') AS state_of_incorporation,
                    NULLIF(trim(classification.entity_type), '') AS entity_type,
                    NULLIF(trim(classification.filer_category), '')
                        AS filer_category,
                    NULLIF(trim(classification.owner_org), '') AS owner_org_cik,
                    NULLIF(trim(identity.name), '') AS name
                FROM read_parquet({sql_literal(str(self.profile_path))})
            )
            SELECT
                cik AS profile_cik,
                raw.sic_code,
                raw.owner_org_cik,
                COALESCE(raw.entity_type, 'operating') AS entity_type,
                COALESCE(raw.filer_category, 'unspecified')
                    AS filer_category_primary,
                raw.state_of_incorporation,
                CASE
                    WHEN raw.state_of_incorporation IS NULL
                        THEN {sql_literal(UNKNOWN_FOREIGN_STATUS)}
                    WHEN upper(raw.state_of_incorporation) IN ({domestic})
                        THEN 'domestic'
                    ELSE 'foreign'
                END AS foreign_status,
                CASE
                    WHEN raw.state_of_incorporation IS NULL
                         OR upper(raw.state_of_incorporation) IN ({domestic})
                        THEN CAST(NULL AS VARCHAR)
                    ELSE raw.state_of_incorporation
                END AS foreign_country_code,
                CASE WHEN raw.owner_org_cik IS NULL
                     THEN 'no_org' ELSE 'has_org' END AS owner_org_presence,
                -- The empty-string fallback is deliberate and must survive the
                -- NULLIF above: `company_family` falls back to `company_name`,
                -- and a NULL there would collapse every name-less registrant
                -- into one over-suppressing bucket instead of a readable ''.
                COALESCE(raw.name, '') AS company_name
            FROM raw
        """

    # -------------------------------------------------------------- stages

    def _write_occurrence_base(
        self,
        con: object,
        union_sql: str,
        staging_dir: Path,
    ) -> int:
        """Write the wide per-occurrence feature table; the only stage touching
        occurrence rows, and every later stage joins it.
        """
        era_expr = self._era_sql("f.report_date")
        family_expr = form_family_sql("f.form")
        size_band_expr = self._size_band_sql("f.reported_size", "a.median_size")
        query = f"""
            WITH source_filings AS ({union_sql}),
            profiles AS ({self._profiles_sql()}),
            size_anchor AS ({self._size_band_anchor_sql(union_sql)})
            SELECT
                f.occurrence_id, f.document_locator_key, f.source_cik, f.accession,
                f.form, {family_expr} AS form_family,
                f.filing_date, f.report_date,
                {era_expr} AS era,
                CASE
                    WHEN f.document_path LIKE '%.htm%' THEN 'htm'
                    WHEN f.document_path LIKE '%.txt%' THEN 'txt'
                    WHEN f.document_path LIKE '%.pdf%' THEN 'pdf'
                    ELSE 'other'
                END AS suffix,
                f.primary_document, f.document_path, f.archive_url,
                f.document_path_source, f.reported_size,
                {size_band_expr} AS size_band,
                f.is_xbrl, f.is_inline_xbrl, f.is_xbrl_numeric,
                CASE WHEN f.reported_size IS NOT NULL
                      AND f.reported_size < {int(self.options["stub_size_threshold"])}
                     THEN 'true' ELSE 'false' END AS stub_suspect,
                CASE WHEN f.is_inline_xbrl THEN 'inline_xbrl'
                     WHEN f.is_xbrl THEN 'xbrl_only'
                     ELSE 'no_xbrl' END AS xbrl_state,
                p.sic_code, p.owner_org_presence, p.foreign_status,
                p.foreign_country_code, p.state_of_incorporation,
                p.entity_type, p.filer_category_primary,
                COALESCE(cf.company_family, p.company_name, '') AS company_family
            FROM source_filings f
            LEFT JOIN profiles p ON f.source_cik = p.profile_cik
            LEFT JOIN {self._family_relation_sql()} cf
                   ON f.source_cik = cf.cik
            LEFT JOIN size_anchor a ON a.form_family = {family_expr}
        """
        return copy_query_to_parquet(
            con, query, staging_dir / "occurrence_base.parquet", self.row_group_size
        )

    def _write_lifecycle(self, con: object, union_sql: str, staging_dir: Path) -> int:
        gap_years = int(self.options["gap_years"])
        grace_years = int(self.options["cessation_grace_years"])
        query = f"""
            WITH source_filings AS ({union_sql}),
            dated AS (
                SELECT source_cik,
                       CAST(substring(report_date, 1, 4) AS INTEGER) AS year
                FROM source_filings
                WHERE report_date IS NOT NULL AND length(report_date) >= 4
            ),
            max_year_overall AS (SELECT MAX(year) AS global_max FROM dated),
            distinct_years AS (SELECT DISTINCT source_cik, year FROM dated),
            year_pairs AS (
                SELECT source_cik, year,
                       LEAD(year) OVER (PARTITION BY source_cik ORDER BY year) AS next_year
                FROM distinct_years
            ),
            cik_metrics AS (
                SELECT
                    source_cik,
                    MIN(year) AS min_year, MAX(year) AS max_year,
                    COUNT(DISTINCT year) AS active_years,
                    BOOL_OR(next_year IS NOT NULL AND (next_year - year) >= {gap_years})
                        AS has_gap
                FROM year_pairs GROUP BY source_cik
            )
            SELECT
                m.source_cik,
                COALESCE(m.has_gap, false) AS has_revival_gap,
                CASE
                    WHEN m.active_years <= 2
                         AND m.max_year >= (g.global_max - 2)
                        THEN 'short_recent_history'
                    WHEN (g.global_max - m.max_year) >= {grace_years}
                        THEN 'ceased_filing_observed'
                    WHEN (g.global_max - m.max_year) <= 1
                        THEN 'right_censored_active'
                    ELSE 'intermediate_or_dormant'
                END AS lifecycle_class
            FROM cik_metrics m CROSS JOIN max_year_overall g
        """
        return copy_query_to_parquet(
            con, query, staging_dir / "lifecycle.parquet", self.row_group_size
        )

    def _write_occurrence_features(self, con: object, staging_dir: Path) -> int:
        base = sql_literal(str(staging_dir / "occurrence_base.parquet"))
        lifecycle = sql_literal(str(staging_dir / "lifecycle.parquet"))
        base_projection = ", ".join(f"o.{column}" for column in OCCURRENCE_BASE_COLUMNS)
        query = f"""
            WITH occurrences AS (SELECT * FROM read_parquet({base}))
            SELECT
                {base_projection},
                COALESCE(l.has_revival_gap, false) AS has_revival_gap,
                COALESCE(l.lifecycle_class, 'unknown') AS lifecycle_class
            FROM occurrences o
            LEFT JOIN read_parquet({lifecycle}) l ON o.source_cik = l.source_cik
        """
        return copy_query_to_parquet(
            con,
            query,
            staging_dir / OCCURRENCE_FEATURES_FILE,
            self.row_group_size,
        )

    def _write_locator_features(self, con: object, staging_dir: Path) -> int:
        """Collapse occurrences to one row per locator; selection counts documents, so
        co-filed occurrences pick a representative by lowest `occurrence_id`.

        `locator_class` shares that window, so the corpus is partitioned by key once.
        """
        # The frame is stated because a window carrying an ORDER BY defaults to a
        # running RANGE: unframed, the count reads 1 on the first row of every
        # partition, which is the only row `rn = 1` keeps.
        occurrences = sql_literal(str(staging_dir / OCCURRENCE_FEATURES_FILE))
        occurrence_projection = ", ".join(
            f"o.{column}" for column in OCCURRENCE_FEATURE_COLUMNS
        )
        locator_projection = ", ".join(
            _locator_column_expression(column) for column in LOCATOR_FEATURE_COLUMNS
        )
        query = f"""
            WITH ranked AS (
                SELECT {occurrence_projection},
                       ROW_NUMBER() OVER w AS rn,
                       COUNT(*) OVER (
                           w ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS loc_occ_count
                FROM read_parquet({occurrences}) o
                WINDOW w AS (
                    PARTITION BY o.document_locator_key ORDER BY o.occurrence_id
                )
            )
            SELECT {locator_projection}
            FROM ranked WHERE rn = 1
        """
        return copy_query_to_parquet(
            con, query, staging_dir / LOCATOR_FEATURES_FILE, self.row_group_size
        )

    # ---------------------------------------------------------------- build

    def build(self) -> SnapshotPaths:
        """Build the snapshot, or return the existing one for these inputs."""
        forms = sorted(set(self.policy.forms))
        if not forms:
            raise ValueError("no forms configured in policy")

        snapshot_dir = self.snapshot_dir(forms)
        paths = self.paths_for(snapshot_dir)
        if self._is_reusable(paths.manifest):
            return paths
        # Drop a stale manifest before rebuilding, so an interrupted rebuild cannot
        # leave one describing files it did not write.
        paths.manifest.unlink(missing_ok=True)

        # Validate the cheap input before opening a connection, so a missing
        # target directory is reported as itself, not as a downstream IO error.
        target_parts = self._target_part_files()
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        with connect() as con:
            union = self._target_union(forms, target_parts)
            counts["occurrence_rows"] = self._write_occurrence_base(
                con, union, snapshot_dir
            )
            counts["lifecycle_rows"] = self._write_lifecycle(con, union, snapshot_dir)
            counts["occurrence_features"] = self._write_occurrence_features(
                con, snapshot_dir
            )
            counts["locator_features"] = self._write_locator_features(con, snapshot_dir)

        for intermediate in (
            OCCURRENCE_BASE_FILE,
            LIFECYCLE_FILE,
        ):
            (snapshot_dir / intermediate).unlink(missing_ok=True)

        manifest = {
            "snapshot_id": snapshot_dir.name,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "policy_fingerprint": self.policy.policy_fingerprint,
            "family_index_id": self.family_index_id,
            "corpus_id": self.policy.corpus_id,
            "forms": forms,
            "options": self.options,
            "counts": counts,
        }
        atomic_write_text(
            paths.manifest,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        return paths


__all__ = [
    "DEFAULT_CESSATION_GRACE_YEARS",
    "DEFAULT_GAP_YEARS",
    "DEFAULT_STUB_SIZE_THRESHOLD",
    "FEATURE_SCHEMA_VERSION",
    "FORM_FAMILY_SUFFIXES",
    "IDENTITY_COLUMNS",
    "SIZE_BAND_MULTIPLIERS",
    "SIZE_BAND_NAMES",
    "UNKNOWN_FOREIGN_STATUS",
    "UNKNOWN_SIZE_BAND",
    "FeatureSnapshotBuilder",
    "SnapshotPaths",
    "era_of",
    "form_family",
    "form_family_sql",
]
