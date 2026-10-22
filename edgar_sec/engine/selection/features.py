"""Build the content-addressed feature snapshot quota selection reads. Form-family
SQL comes from the same suffix vocabulary as the Python helper, and a snapshot is
reused only while its input fingerprint matches.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import (
    OCCURRENCE_INDEPENDENT_COLUMNS,
)
from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
    TARGET_COLUMNS,
)
from edgar_sec.domain.forms.common.aliases import FORM_FAMILY_SUFFIXES
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.engine.selection.snapshot import (
    SnapshotPaths,
    feature_branch_name,
    load_snapshot_paths,
)
from edgar_sec.foundation.runtime.paths import PARQUET_PART_GLOB, SNAPSHOTS_DIR
from edgar_sec.engine.selection.paths import (
    LIFECYCLE_FILE,
    LOCATOR_BANDS_FILE,
    LOCATOR_FEATURES_FILE,
    OCCURRENCE_INDEPENDENT_FILE,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size

# Bump when feature derivation changes in a way that requires rebuilding
FEATURE_SCHEMA_VERSION = "2.1"
DERIVATION_VERSION = "2.2"

UNMATCHED_ERA = "unknown"

# Every target column except the one projected separately as `source_projection`.
# Derived from the domain schema, so a new target column flows through without a
# second list to update.
IDENTITY_COLUMNS = ", ".join(
    column for column in TARGET_COLUMNS if column != "document_path_source"
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
        row_group_size: int | None = None,
        gap_years: int = DEFAULT_GAP_YEARS,
        cessation_grace_years: int = DEFAULT_CESSATION_GRACE_YEARS,
        stub_size_threshold: int = DEFAULT_STUB_SIZE_THRESHOLD,
        parent_feature_snapshot_id: str | None = None,
        active_target_parts: Sequence[Path] | None = None,
        delta_target_parts: Sequence[Path] | None = None,
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
        self.row_group_size = resolve_row_group_size(row_group_size)
        self.options = _build_options(
            gap_years, cessation_grace_years, stub_size_threshold
        )
        self.options["row_group_size"] = self.row_group_size
        self.parent_feature_snapshot_id = parent_feature_snapshot_id
        self.active_target_parts = tuple(
            Path(path).resolve() for path in (active_target_parts or ())
        )
        self.delta_target_parts = tuple(
            Path(path).resolve() for path in (delta_target_parts or ())
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
        payload = {
            "target_root": str(self.target_root),
            "profile_path": str(self.profile_path),
            "profile_sha256": file_sha256(self.profile_path),
            "row_group_size": self.row_group_size,
            "feature_signature": self.feature_signature(forms),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        }
        return (
            self.output_root / SNAPSHOTS_DIR / f"feature-{canonical_hash(payload)[:32]}"
        )

    def feature_signature(self, forms: Sequence[str] | None = None) -> dict[str, Any]:
        """Return a signature capturing all inputs that affect feature derivation."""
        return {
            "forms": sorted(forms if forms is not None else self.policy.forms),
            "era_bands": [band.to_dict() for band in self.policy.era_bands],
            "family_index_id": self.family_index_id,
            "options": {
                key: value
                for key, value in self.options.items()
                if key != "row_group_size"
            },
            "derivation_version": DERIVATION_VERSION,
        }

    def _is_parent_compatible(self) -> bool:
        """Whether prior independent rows can be inherited without stale enrichment."""
        if self.parent_feature_snapshot_id is None:
            return False
        try:
            parent = self._load_parent_snapshot()
        except (OSError, ValueError, RuntimeError):
            return False
        recorded = parent.manifest
        if recorded.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            return False
        if recorded.get("feature_signature") != self.feature_signature():
            return False
        artifact_parts = (
            *parent.occurrence_parts,
            *parent.locator_band_parts,
            *parent.lifecycle_parts,
            *parent.locator_feature_parts,
        )
        if not parent.occurrence_parts or not all(
            path.is_file() for path in artifact_parts
        ):
            return False
        return self._inherited_profiles_unchanged(recorded, parent.occurrence_parts)

    def _load_parent_snapshot(self) -> SnapshotPaths:
        """Load parent feature metadata and inherited relation parts."""
        if self.parent_feature_snapshot_id is None:
            raise RuntimeError("no parent feature snapshot registered")
        parent_dir = self.output_root / SNAPSHOTS_DIR / self.parent_feature_snapshot_id
        return self._snapshot_paths(parent_dir)

    def _inherited_profiles_unchanged(
        self, parent: dict[str, Any], occurrence_parts: Sequence[Path]
    ) -> bool:
        old_profile = Path(str(parent.get("profile_path") or ""))
        if not old_profile.is_file():
            return False
        inherited_parts = ", ".join(sql_literal(str(path)) for path in occurrence_parts)
        compared = (
            "sic_code",
            "owner_org_cik",
            "entity_type",
            "filer_category_primary",
            "state_of_incorporation",
            "foreign_status",
            "foreign_country_code",
            "owner_org_presence",
            "company_name",
        )
        old_values = ", ".join(f"old.{column}" for column in compared)
        new_values = ", ".join(f"new.{column}" for column in compared)
        query = f"""
            WITH inherited AS (
                SELECT DISTINCT source_cik
                FROM read_parquet([{inherited_parts}])
            ),
            old_profiles AS (
                SELECT * FROM ({self._profiles_sql(old_profile)})
            ),
            new_profiles AS (
                SELECT * FROM ({self._profiles_sql()})
            ),
            compared AS (
                SELECT inherited.source_cik,
                       ({old_values}) AS old_values,
                       ({new_values}) AS new_values
                FROM inherited
                LEFT JOIN old_profiles old
                       ON inherited.source_cik = old.profile_cik
                LEFT JOIN new_profiles new
                       ON inherited.source_cik = new.profile_cik
            )
            SELECT COUNT(*) FROM compared
            WHERE old_values IS DISTINCT FROM new_values
        """
        with connect() as con:
            row = con.execute(query).fetchone()
        return bool(row and int(row[0]) == 0)

    def _target_part_files(self) -> list[Path]:
        if self.active_target_parts:
            parts = list(self.active_target_parts)
        else:
            parts = sorted(self.target_root.glob(PARQUET_PART_GLOB))
        if not parts:
            raise FileNotFoundError(f"no target part files found in {self.target_root}")
        return parts

    def _new_target_part_files(self, incremental: bool) -> list[Path]:
        if incremental:
            parts = list(self.delta_target_parts)
            if not parts:
                raise FileNotFoundError("delta catalog has no new target part files")
        else:
            parts = self._target_part_files()
        missing = [path for path in parts if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"target part file is missing: {missing[0]}")
        return parts

    def _snapshot_paths(self, snapshot_dir: Path) -> SnapshotPaths:
        return load_snapshot_paths(snapshot_dir)

    def paths_for(self, snapshot_dir: Path) -> SnapshotPaths:
        return self._snapshot_paths(snapshot_dir)

    def _is_reusable(self, snapshot_id: str) -> bool:
        """Whether a registered feature node still matches current inputs."""
        try:
            snapshot = self._snapshot_paths(
                self.output_root / SNAPSHOTS_DIR / snapshot_id
            )
            recorded = snapshot.manifest
        except (OSError, ValueError):
            return False
        if recorded.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            return False
        if recorded.get("feature_signature") != self.feature_signature():
            return False
        if recorded.get("profile_sha256") != file_sha256(self.profile_path):
            return False
        artifacts = (
            *snapshot.occurrence_parts,
            *snapshot.locator_band_parts,
            *snapshot.lifecycle_parts,
            *snapshot.locator_feature_parts,
        )
        if not all(path.is_file() for path in artifacts):
            return False
        from edgar_sec.infra.storage.dag.catalog import DAGCatalog

        catalog = DAGCatalog(self.output_root / SNAPSHOTS_DIR)
        catalog.write_pointer(
            feature_branch_name(self.feature_signature()), snapshot_id
        )
        return True

    # ----------------------------------------------------------------- SQL

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

    def _form_family_sql(self, column: str) -> str:
        return form_family_sql(column)

    def _size_band_anchor_sql(
        self, union_sql: str, family_relation_sql: str | None = None
    ) -> str:
        """Use one canonical size observation per document in each form family."""
        family_expr = form_family_sql("form")
        filter_families = (
            ""
            if family_relation_sql is None
            else f"AND {family_expr} IN ({family_relation_sql})"
        )
        return f"""
            WITH locator_sizes AS (
                SELECT {family_expr} AS form_family,
                       reported_size,
                       ROW_NUMBER() OVER (
                           PARTITION BY document_locator_key ORDER BY occurrence_id
                       ) AS representative_rank
                FROM ({union_sql})
                WHERE reported_size IS NOT NULL
                {filter_families}
            )
            SELECT form_family, median(reported_size) AS median_size
            FROM locator_sizes
            WHERE representative_rank = 1
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

    def _profiles_sql(self, profile_path: Path | None = None) -> str:
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
                FROM read_parquet({sql_literal(str(profile_path or self.profile_path))})
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

    def _write_occurrence_independent(
        self,
        con: object,
        union_sql: str,
        staging_dir: Path,
    ) -> int:
        """Write row-local occurrence features without population-dependent columns."""
        era_expr = self._era_sql("COALESCE(NULLIF(f.report_date, ''), f.filing_date)")
        family_expr = form_family_sql("f.form")
        query = f"""
            WITH source_filings AS ({union_sql}),
            profiles AS ({self._profiles_sql()})
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
                f.document_path_source, f.primary_exhibit_like, f.reported_size,
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
        """
        return copy_query_to_parquet(
            con,
            query,
            staging_dir / OCCURRENCE_INDEPENDENT_FILE,
            self.row_group_size,
        )

    def _write_locator_bands(
        self,
        con: object,
        union_sql: str,
        staging_dir: Path,
        *,
        family_relation_sql: str | None = None,
        locator_keys_sql: str | None = None,
        anchor_family_relation_sql: str | None = None,
        full: bool = True,
    ) -> int:
        family_expr = form_family_sql("form")
        size_band_expr = self._size_band_sql("r.reported_size", "a.median_size")
        filters: list[str] = []
        if family_relation_sql is not None:
            filters.append(f"r.form_family IN ({family_relation_sql})")
        if locator_keys_sql is not None:
            filters.append(f"r.document_locator_key IN ({locator_keys_sql})")
        where = " OR ".join(filters) if filters else ("TRUE" if full else "FALSE")
        source_filters: list[str] = []
        if family_relation_sql is not None:
            source_filters.append(f"{family_expr} IN ({family_relation_sql})")
        if locator_keys_sql is not None:
            source_filters.append(f"document_locator_key IN ({locator_keys_sql})")
        source_filter = (
            " OR ".join(source_filters)
            if source_filters
            else ("TRUE" if full else "FALSE")
        )
        query = f"""
            WITH source_filings AS ({union_sql}),
            size_anchor AS (
                {self._size_band_anchor_sql(union_sql, anchor_family_relation_sql)}
            ),
            locator_rows AS (
                SELECT document_locator_key,
                       {family_expr} AS form_family,
                       reported_size,
                       ROW_NUMBER() OVER (
                           PARTITION BY document_locator_key ORDER BY occurrence_id
                       ) AS representative_rank
                FROM source_filings
                WHERE {source_filter}
            )
            SELECT r.document_locator_key,
                   {size_band_expr} AS size_band
            FROM locator_rows r
            LEFT JOIN size_anchor a ON a.form_family = r.form_family
            WHERE r.representative_rank = 1 AND ({where})
        """
        return copy_query_to_parquet(
            con,
            query,
            staging_dir / LOCATOR_BANDS_FILE,
            self.row_group_size,
        )

    def _write_lifecycle(
        self,
        con: object,
        union_sql: str,
        staging_dir: Path,
        global_max_year: int | None,
        changed_ciks_sql: str | None = None,
    ) -> int:
        gap_years = int(self.options["gap_years"])
        grace_years = int(self.options["cessation_grace_years"])
        changed = f"AND source_cik IN ({changed_ciks_sql})" if changed_ciks_sql else ""
        global_max = (
            "CAST(NULL AS INTEGER)" if global_max_year is None else str(global_max_year)
        )
        query = f"""
            WITH source_filings AS ({union_sql}),
            max_year_overall AS (SELECT {global_max} AS global_max),
            dated AS (
                SELECT source_cik,
                       CAST(substring(report_date, 1, 4) AS INTEGER) AS year
                FROM source_filings
                WHERE report_date IS NOT NULL AND length(report_date) >= 4
                {changed}
            ),
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
            con, query, staging_dir / LIFECYCLE_FILE, self.row_group_size
        )

    def _global_max_year(self, con: object, union_sql: str) -> int | None:
        row = con.execute(
            "SELECT MAX(try_cast(substring(report_date, 1, 4) AS INTEGER)) "
            f"FROM ({union_sql}) WHERE report_date IS NOT NULL AND length(report_date) >= 4"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def _write_locator_features(
        self,
        con: object,
        staging_dir: Path,
        occurrence_relation: str,
        affected_keys_sql: str | None = None,
    ) -> int:
        """Collapse occurrences to one row per locator; selection counts documents, so
        co-filed occurrences pick a representative by lowest `occurrence_id`.

        `locator_class` shares that window, so the corpus is partitioned by key once.
        """
        # The frame is stated because a window carrying an ORDER BY defaults to a
        # running RANGE: unframed, the count reads 1 on the first row of every
        # partition, which is the only row `rn = 1` keeps.
        occurrence_projection = ", ".join(
            f"o.{column}" for column in OCCURRENCE_FEATURE_COLUMNS
        )
        locator_projection = ", ".join(
            _locator_column_expression(column) for column in LOCATOR_FEATURE_COLUMNS
        )
        filter = (
            "JOIN affected_keys a USING (document_locator_key)"
            if affected_keys_sql is not None
            else ""
        )
        affected = (
            f"affected_keys AS ({affected_keys_sql}),"
            if affected_keys_sql is not None
            else ""
        )
        query = f"""
            WITH {affected}
            ranked AS (
                SELECT {occurrence_projection},
                       ROW_NUMBER() OVER w AS rn,
                       COUNT(*) OVER (
                           w ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS loc_occ_count
                FROM {occurrence_relation} o {filter}
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

    def build(self, progress: Any = None) -> SnapshotPaths:
        from edgar_sec.engine.selection.snapshot_build import build_snapshot

        return build_snapshot(self, FEATURE_SCHEMA_VERSION, progress)


__all__ = [
    "DEFAULT_CESSATION_GRACE_YEARS",
    "DEFAULT_GAP_YEARS",
    "DEFAULT_STUB_SIZE_THRESHOLD",
    "FEATURE_SCHEMA_VERSION",
    "DERIVATION_VERSION",
    "FORM_FAMILY_SUFFIXES",
    "IDENTITY_COLUMNS",
    "SIZE_BAND_MULTIPLIERS",
    "SIZE_BAND_NAMES",
    "UNKNOWN_FOREIGN_STATUS",
    "UNKNOWN_SIZE_BAND",
    "FeatureSnapshotBuilder",
    "era_of",
    "form_family",
    "form_family_sql",
]
