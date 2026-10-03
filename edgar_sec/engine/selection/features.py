"""Build the content-addressed feature snapshot used by quota selection.

Pure helpers map filing forms and dates to selection dimensions.
``FeatureSnapshotBuilder`` resolves profile and occurrence fields, writes the
snapshot, and reuses it when its input fingerprint matches. Form-family SQL is
generated from the same suffix vocabulary as the Python helper; required source
columns are validated rather than silently replaced with nulls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.domain.forms.common.aliases import FORM_FAMILY_SUFFIXES
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.engine.company_family.clustering import CompanyFamilyIndex
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import copy_query_to_parquet, sql_literal
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE

FEATURE_SCHEMA_VERSION = "1.0"

# Amendment and submission suffixes stripped when collapsing a raw form string
# to its base family are owned by domain.forms.families and imported here, so
# the engine's collapse order cannot drift from the domain registry's.

UNMATCHED_ERA = "unknown"

# Every target column except the one projected separately as `source_projection`.
# Derived from the domain schema rather than restated, so a new target column
# flows into the snapshot without a second list to update.
IDENTITY_COLUMNS = ", ".join(
    column for column in TARGET_COLUMNS if column != "document_path_source"
)

DEFAULT_GAP_YEARS = 3
DEFAULT_CESSATION_GRACE_YEARS = 5
DEFAULT_STUB_SIZE_THRESHOLD = 100_000

SIZE_BAND_MULTIPLIERS = (0.25, 1.0, 4.0, 16.0)
SIZE_BAND_NAMES = ("very_small", "small", "median", "large", "very_large")
UNKNOWN_SIZE_BAND = "unknown"
UNKNOWN_FOREIGN_STATUS = "unknown"

_FAMILY_MAP_DDL = (
    "CREATE OR REPLACE TEMP TABLE company_family_map "
    "(cik VARCHAR, company_family VARCHAR)"
)

_SQL_COLUMN_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# Named rather than inlined so a published plan can name what it excluded.
_FEATURE_MANIFEST_NAME = "feature_snapshot.json"
_OCCURRENCE_FEATURES_NAME = "occurrence_features.parquet"
_LOCATOR_FEATURES_NAME = "locator_features.parquet"


def form_family(form: str) -> str:
    """Collapse amendment and submission suffixes to a base form family.

    ``10-K/A`` and ``10-K_A`` both become ``10-K``. A form that is *entirely*
    suffixes (``/A``) collapses to the empty string, and the original is
    returned rather than an empty dimension value.
    """
    base = form.upper().strip()
    for suffix in FORM_FAMILY_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form


def form_family_sql(column: str) -> str:
    """Return a SQL expression equivalent to :func:`form_family`.

    Generated from :data:`FORM_FAMILY_SUFFIXES` rather than written by hand, so
    the SQL and Python forms cannot disagree. Each ``removesuffix`` becomes one
    ``$``-anchored ``regexp_replace``, applied in the same order, and the empty
    fallback is reproduced with a ``CASE``.
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
    """Map a report date onto the first matching policy era band.

    An empty, absent, or non-numeric-prefix date is ``unknown`` rather than an
    error: a filing with no usable report date is a real outcome, and bucketing
    it as unknown keeps it visible instead of dropping the row.
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
    """The four files that make up one feature snapshot."""

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
        self.row_group_size = row_group_size
        self.options = _build_options(
            gap_years, cessation_grace_years, stub_size_threshold
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
        }
        return self.output_root / "snapshots" / canonical_hash(payload)[:32]

    def paths_for(self, snapshot_dir: Path) -> SnapshotPaths:
        return SnapshotPaths(
            snapshot_dir=snapshot_dir,
            manifest=snapshot_dir / _FEATURE_MANIFEST_NAME,
            occurrence_features=snapshot_dir / _OCCURRENCE_FEATURES_NAME,
            locator_features=snapshot_dir / _LOCATOR_FEATURES_NAME,
        )

    # ----------------------------------------------------------------- SQL

    def _target_part_files(self) -> list[Path]:
        parts = sorted(self.target_root.glob("part-*.parquet"))
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
        """Return a relation of (form_family, median_size) for every family.

        One row per family, so the anchor is a rounding error against the
        occurrence rows it will be joined to -- measured at 243 rows against
        961,072 on a single shard. Keyed on ``form_family`` rather than ``form``
        so amendment variants pool into one family and the median rests on more
        rows; era is deliberately absent, because era is already an independent
        stratum and adding it would fragment the anchor roughly fifteen-fold
        for no gain in balance.
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
        """Band a size relative to its own family's median.

        Row-local: once the anchor exists this is pure arithmetic, so it folds
        into the occurrence base projection instead of needing its own pass, a
        side table, and a join back.
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
        """Project the nested Phase 1 profile schema onto the flat feature shape.

        Profile text fields use an empty string for absent values. The ``raw``
        CTE normalizes blanks to NULL once so downstream ``COALESCE``, null
        checks, and postal-code membership tests treat them as missing.

        ``foreign_status`` uses the jurisdiction vocabulary and reports a
        missing state as ``unknown``. An absent value must not be counted as
        evidence that a registrant is foreign.
        """
        domestic = ", ".join(sql_literal(code) for code in sorted(STATE_POSTAL_CODES))
        return f"""
            WITH raw AS (
                SELECT
                    cik,
                    NULLIF(trim(classification.sic_code), '') AS sic_code,
                    NULLIF(trim(classification.sic_description), '') AS sic_description,
                    NULLIF(trim(classification.owner_org), '') AS owner_org_cik,
                    NULLIF(trim(classification.entity_type), '') AS entity_type,
                    NULLIF(trim(classification.filer_category), '')
                        AS filer_category,
                    NULLIF(trim(incorporation.state), '') AS state_of_incorporation,
                    NULLIF(trim(addresses.business.state_or_country), '')
                        AS state_of_business,
                    NULLIF(trim(identity.name), '') AS name
                FROM read_parquet({sql_literal(str(self.profile_path))})
            )
            SELECT
                cik AS profile_cik,
                raw.sic_code,
                raw.sic_description,
                raw.owner_org_cik,
                COALESCE(raw.entity_type, 'operating') AS entity_type,
                COALESCE(raw.filer_category, 'unspecified')
                    AS filer_category_primary,
                raw.state_of_incorporation,
                raw.state_of_business,
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
        """Write the wide per-occurrence feature table.

        This is the expensive stage: it is the only one that touches the
        occurrence rows, and every later stage joins against its output.
        """
        family_index = CompanyFamilyIndex.from_existing_profiles(self.profile_path)
        con.execute(_FAMILY_MAP_DDL)
        con.executemany(
            "INSERT INTO company_family_map VALUES (?, ?)",
            [[cik, info.family_key] for cik, info in family_index.cik_to_info.items()],
        )

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
                CASE WHEN f.report_date IS NOT NULL AND length(f.report_date) >= 4
                     THEN CAST(substring(f.report_date, 1, 4) AS INTEGER)
                     ELSE NULL END AS report_year,
                CASE WHEN f.filing_date IS NOT NULL AND length(f.filing_date) >= 4
                     THEN CAST(substring(f.filing_date, 1, 4) AS INTEGER)
                     ELSE NULL END AS filing_year,
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
                p.sic_code, p.sic_description, p.owner_org_cik,
                p.owner_org_presence, p.foreign_status, p.foreign_country_code,
                p.state_of_incorporation, p.state_of_business,
                p.entity_type, p.filer_category_primary, p.company_name,
                COALESCE(cf.company_family, p.company_name, '') AS company_family
            FROM source_filings f
            LEFT JOIN profiles p ON f.source_cik = p.profile_cik
            LEFT JOIN company_family_map cf ON f.source_cik = cf.cik
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
                m.min_year AS first_report_year,
                m.max_year AS last_report_year,
                m.active_years,
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

    def _write_cross_form(
        self, con: object, union_sql: str, forms: Sequence[str], staging_dir: Path
    ) -> int:
        """Classify each CIK by whether its anchor and comparison forms are live.

        With no anchor/comparison forms configured the stage writes a
        schema-correct zero-row file rather than skipping, so the downstream
        join is unconditional.
        """
        anchor_set = set(self.policy.anchor_forms)
        comparison_set = set(self.policy.comparison_forms)
        if not anchor_set or not comparison_set:
            return copy_query_to_parquet(
                con,
                "SELECT CAST(NULL AS VARCHAR) AS source_cik, "
                "'unspecified' AS anchor_status, "
                "'unspecified' AS comparison_status WHERE 1 = 0",
                staging_dir / "cross_form.parquet",
                self.row_group_size,
            )

        anchor_list = ", ".join(sql_literal(form) for form in sorted(anchor_set))
        comparison_list = ", ".join(
            sql_literal(form) for form in sorted(comparison_set)
        )
        query = f"""
            WITH source_filings AS ({union_sql}),
            dated AS (
                SELECT source_cik, form,
                       CAST(substring(report_date, 1, 4) AS INTEGER) AS year
                FROM source_filings
                WHERE report_date IS NOT NULL AND length(report_date) >= 4
            ),
            anchor_dates AS (
                SELECT source_cik, MAX(year) AS last_anchor_year
                FROM dated WHERE form IN ({anchor_list}) GROUP BY source_cik
            ),
            comparison_dates AS (
                SELECT source_cik, MAX(year) AS last_comp_year
                FROM dated WHERE form IN ({comparison_list}) GROUP BY source_cik
            ),
            global_max AS (SELECT MAX(year) AS global_max_year FROM dated)
            SELECT
                c.source_cik,
                CASE
                    WHEN a.last_anchor_year IS NULL THEN 'no_anchor'
                    WHEN (g.global_max_year - a.last_anchor_year) >= 5
                        THEN 'anchor_ceased_observed'
                    ELSE 'anchor_active'
                END AS anchor_status,
                CASE
                    WHEN k.last_comp_year IS NULL THEN 'no_comparison'
                    WHEN a.last_anchor_year IS NOT NULL
                         AND k.last_comp_year > a.last_anchor_year
                        THEN 'comparison_active_after_anchor'
                    ELSE 'comparison_aligned_or_earlier'
                END AS comparison_status
            FROM (SELECT DISTINCT source_cik FROM dated) c
            LEFT JOIN anchor_dates a ON c.source_cik = a.source_cik
            LEFT JOIN comparison_dates k ON c.source_cik = k.source_cik
            CROSS JOIN global_max g
        """
        return copy_query_to_parquet(
            con, query, staging_dir / "cross_form.parquet", self.row_group_size
        )

    def _write_occurrence_features(self, con: object, staging_dir: Path) -> int:
        base = sql_literal(str(staging_dir / "occurrence_base.parquet"))
        lifecycle = sql_literal(str(staging_dir / "lifecycle.parquet"))
        cross_form = sql_literal(str(staging_dir / "cross_form.parquet"))
        query = f"""
            WITH occurrences AS (SELECT * FROM read_parquet({base})),
            occ_per_locator AS (
                SELECT document_locator_key, COUNT(*) AS loc_occ_count
                FROM occurrences GROUP BY document_locator_key
            ),
            occ_per_accession AS (
                SELECT accession, COUNT(*) AS acc_occ_count
                FROM occurrences GROUP BY accession
            )
            SELECT
                o.*,
                COALESCE(l.first_report_year, o.report_year) AS first_report_year,
                COALESCE(l.last_report_year, o.report_year) AS last_report_year,
                COALESCE(l.active_years, 1) AS active_years,
                COALESCE(l.has_revival_gap, false) AS has_revival_gap,
                COALESCE(l.lifecycle_class, 'unknown') AS lifecycle_class,
                COALESCE(c.anchor_status, 'unspecified') AS anchor_status,
                COALESCE(c.comparison_status, 'unspecified') AS comparison_status,
                CASE WHEN la.acc_occ_count = 1 THEN 'single'
                     WHEN la.acc_occ_count BETWEEN 2 AND 3 THEN 'low_2_to_3'
                     ELSE 'high_4_plus' END AS accession_class,
                CASE WHEN ll.loc_occ_count = 1 THEN 'single'
                     WHEN ll.loc_occ_count BETWEEN 2 AND 3 THEN 'low_2_to_3'
                     ELSE 'high_4_plus' END AS locator_class
            FROM occurrences o
            LEFT JOIN read_parquet({lifecycle}) l ON o.source_cik = l.source_cik
            LEFT JOIN read_parquet({cross_form}) c ON o.source_cik = c.source_cik
            LEFT JOIN occ_per_locator ll
                   ON o.document_locator_key = ll.document_locator_key
            LEFT JOIN occ_per_accession la ON o.accession = la.accession
        """
        return copy_query_to_parquet(
            con,
            query,
            staging_dir / _OCCURRENCE_FEATURES_NAME,
            self.row_group_size,
        )

    def _write_locator_features(self, con: object, staging_dir: Path) -> int:
        """Collapse occurrences to one row per document locator.

        A locator can carry several occurrences when two registrants co-file
        one document. Selection counts *documents*, not rows, so the collapse
        picks a single representative by the lowest ``occurrence_id`` -- an
        arbitrary but total order, which is all determinism requires.
        """
        occurrences = sql_literal(str(staging_dir / _OCCURRENCE_FEATURES_NAME))
        query = f"""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY document_locator_key ORDER BY occurrence_id
                ) AS rn
                FROM read_parquet({occurrences})
            )
            SELECT
                document_locator_key, form, form_family, era, suffix, xbrl_state,
                size_band, owner_org_presence, foreign_status, foreign_country_code,
                entity_type, filer_category_primary, lifecycle_class, has_revival_gap,
                locator_class, stub_suspect, anchor_status, comparison_status,
                reported_size, report_year, filing_year, filing_date,
                report_date, primary_document, document_path, archive_url,
                document_path_source,
                source_cik AS representative_cik,
                accession AS representative_accession,
                sic_code, company_name, company_family
            FROM ranked WHERE rn = 1
        """
        return copy_query_to_parquet(
            con, query, staging_dir / _LOCATOR_FEATURES_NAME, self.row_group_size
        )

    # ---------------------------------------------------------------- build

    def build(self) -> SnapshotPaths:
        """Build the snapshot, or return the existing one for these inputs."""
        forms = sorted(set(self.policy.forms))
        if not forms:
            raise ValueError("no forms configured in policy")

        snapshot_dir = self.snapshot_dir(forms)
        paths = self.paths_for(snapshot_dir)
        if paths.manifest.is_file():
            return paths

        # Validate the cheap input before opening a connection or reading the
        # profile dataset, so a missing target directory is reported as itself
        # rather than as a downstream IO error.
        target_parts = self._target_part_files()
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        with connect() as con:
            union = self._target_union(forms, target_parts)
            counts["occurrence_rows"] = self._write_occurrence_base(
                con, union, snapshot_dir
            )
            counts["lifecycle_rows"] = self._write_lifecycle(con, union, snapshot_dir)
            counts["cross_form_rows"] = self._write_cross_form(
                con, union, forms, snapshot_dir
            )
            counts["occurrence_features"] = self._write_occurrence_features(
                con, snapshot_dir
            )
            counts["locator_features"] = self._write_locator_features(con, snapshot_dir)

        for intermediate in (
            "occurrence_base.parquet",
            "lifecycle.parquet",
            "cross_form.parquet",
        ):
            (snapshot_dir / intermediate).unlink(missing_ok=True)

        manifest = {
            "snapshot_id": snapshot_dir.name,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "policy_fingerprint": self.policy.policy_fingerprint,
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
