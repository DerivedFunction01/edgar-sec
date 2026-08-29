"""Immutable occurrence- and locator-level feature snapshot builder for Phase 02.

Computes multi-dimensional features over catalog artifacts (filing_targets,
company_profiles, filing_occurrence_sources) for policy-driven fixture
selection without full memory materialization.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defs.runtime.resources import derive_resources
from defs.storage import DuckDBStaging

from .selection_policy import EraBand, SelectionPolicy

FEATURE_SCHEMA_VERSION = "1.0"

IDENTITY_COLUMNS = """
    occurrence_id, document_locator_key, source_cik, accession, form,
    is_amendment, filing_date, report_date, primary_document, document_path,
    archive_url, reported_size, is_xbrl, is_inline_xbrl, is_xbrl_numeric
"""


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def form_family(form: str) -> str:
    """Collapse amendment and submission suffixes into the base form family."""
    base = form.upper().strip()
    for suffix in ("_A", "_W", "_POS", "-POS", "MEF", "-W", "/A"):
        base = base.removesuffix(suffix)
    return base.strip("_-") or form


def era_of(report_date: str | None, era_bands: Sequence[EraBand]) -> str:
    """Map a report date string to a policy-defined era band."""
    if not report_date:
        return "unknown"
    year = (
        int(report_date[:4])
        if len(report_date) >= 4 and report_date[:4].isdigit()
        else None
    )
    for band in era_bands:
        if band.matches(year=year, date_str=report_date):
            return band.name
    return "unknown"


@dataclass(frozen=True)
class SnapshotPaths:
    snapshot_dir: Path
    manifest: Path
    occurrence_features: Path
    locator_features: Path


class FeatureSnapshotBuilder:
    """Build an immutable feature snapshot for target forms defined by policy."""

    def __init__(
        self,
        target_root: str | Path,
        profile_path: str | Path,
        output_root: str | Path,
        policy: SelectionPolicy,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | Path | None = None,
        gap_years: int = 3,
        cessation_grace_years: int = 5,
        stub_size_threshold: int = 100_000,
    ) -> None:
        if gap_years < 2:
            raise ValueError("gap_years must be at least 2")
        if cessation_grace_years < 1:
            raise ValueError("cessation_grace_years must be at least 1")
        self.target_root = Path(target_root).resolve()
        self.profile_path = Path(profile_path).resolve()
        self.output_root = Path(output_root).resolve()
        self.policy = policy
        res = derive_resources()
        self.threads = threads if threads is not None else res.threads
        self.memory_limit = memory_limit or res.memory_limit
        self.temp_directory = (
            Path(temp_directory).resolve()
            if temp_directory
            else Path(res.temp_directory).resolve()
        )
        self.options = {
            "gap_years": gap_years,
            "cessation_grace_years": cessation_grace_years,
            "stub_size_threshold": stub_size_threshold,
        }

    def _target_union(self, forms: list[str]) -> str:
        selects = []
        for form in sorted(forms):
            form_part = form.replace("/", "_")
            path = self.target_root / f"form={form_part}" / "data.parquet"
            if not path.exists():
                path = self.target_root / f"form={form}" / "data.parquet"
            if not path.exists():
                raise FileNotFoundError(
                    f"missing target partition for form {form}: {path}"
                )
            selects.append(
                f"SELECT '{form}' AS catalog_form, {IDENTITY_COLUMNS} FROM read_parquet('{path}')"
            )
        return " UNION ALL ".join(selects)

    def snapshot_dir(self, forms: list[str]) -> Path:
        payload = {
            "target_root": str(self.target_root),
            "profile_path": str(self.profile_path),
            "forms": sorted(forms),
            "options": self.options,
            "policy_fingerprint": self.policy.policy_fingerprint,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:32]
        return self.output_root / "snapshots" / digest

    def _paths(self, snapshot_dir: Path) -> SnapshotPaths:
        return SnapshotPaths(
            snapshot_dir=snapshot_dir,
            manifest=snapshot_dir / "snapshot.json",
            occurrence_features=snapshot_dir / "occurrence_features.parquet",
            locator_features=snapshot_dir / "locator_features.parquet",
        )

    def build(self) -> SnapshotPaths:
        """Build or reuse the immutable snapshot for the policy forms."""
        selected = sorted(set(self.policy.forms))
        if not selected:
            raise ValueError("no forms configured in policy")
        snapshot_dir = self.snapshot_dir(selected)
        paths = self._paths(snapshot_dir)
        if paths.manifest.exists():
            return paths

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        db_file = snapshot_dir / "staging_features.duckdb"
        try:
            db_file.unlink(missing_ok=True)
        except OSError:
            pass
        with DuckDBStaging(
            db_file,
            threads=self.threads,
            memory_limit=self.memory_limit,
            temp_directory=self.temp_directory,
        ) as staging:
            union = self._target_union(selected)
            counts["occurrence_rows"] = self._write_occurrence_base(
                staging, union, snapshot_dir
            )
            counts["lifecycle_rows"] = self._write_lifecycle(
                staging, union, snapshot_dir
            )
            counts["size_band_rows"] = self._write_size_bands(
                staging, union, snapshot_dir
            )
            counts["cross_form_rows"] = self._write_cross_form(
                staging, union, selected, snapshot_dir
            )
            counts["occurrence_features"] = self._write_occurrence_features(
                staging, snapshot_dir
            )
            counts["locator_features"] = self._write_locator_features(
                staging, snapshot_dir
            )
            for stage in (
                "occurrence_base.parquet",
                "lifecycle.parquet",
                "size_bands.parquet",
                "cross_form.parquet",
            ):
                (snapshot_dir / stage).unlink(missing_ok=True)

        manifest = {
            "snapshot_id": snapshot_dir.name,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "forms": selected,
            "options": self.options,
            "counts": counts,
        }
        paths.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return paths

    def _sql_era_of(self, col: str) -> str:
        cases = []
        for band in self.policy.era_bands:
            conds = []
            if band.start_year is not None:
                conds.append(
                    f"CAST(substring({col}, 1, 4) AS INTEGER) >= {band.start_year}"
                )
            if band.end_year is not None:
                conds.append(
                    f"CAST(substring({col}, 1, 4) AS INTEGER) < {band.end_year}"
                )
            if band.start_date is not None:
                conds.append(f"{col} >= '{band.start_date}'")
            if band.end_date is not None:
                conds.append(f"{col} <= '{band.end_date}'")
            if conds:
                cases.append(f"WHEN {' AND '.join(conds)} THEN '{band.name}'")
        if not cases:
            return "'unknown'"
        return f"CASE WHEN {col} IS NULL OR length({col}) < 4 THEN 'unknown' {' '.join(cases)} ELSE 'unknown' END"

    def _sql_form_family(self, col: str) -> str:
        return f"TRIM('_-' FROM REGEXP_REPLACE(UPPER(TRIM({col})), '(/A|_A|_W|_POS|-POS|MEF|-W)$', ''))"

    def _write_occurrence_base(
        self, staging: DuckDBStaging, union_sql: str, snapshot_dir: Path
    ) -> int:
        dest = snapshot_dir / "occurrence_base.parquet"
        stub_threshold = int(self.options["stub_size_threshold"])
        from defs.storage import parquet_column_names

        from .company_family import CompanyFamilyIndex

        # Build company family index
        family_index: CompanyFamilyIndex
        seed_path = Path(self.policy.seed_cik_path)
        if (
            not seed_path.is_file()
            and not seed_path.is_absolute()
            and (Path.cwd() / seed_path).is_file()
        ):
            seed_path = Path.cwd() / seed_path
        if seed_path.is_file():
            family_index = CompanyFamilyIndex.build_from_seed(seed_path)
        else:
            prof_records = staging.execute(
                f"SELECT LPAD(CAST(cik AS VARCHAR), 10, '0'), COALESCE(identity.name, '') FROM read_parquet('{self.profile_path}')"
            )
            family_index = CompanyFamilyIndex.build_from_records(
                [(r[0], r[1]) for r in prof_records]
            )

        staging.execute(
            "CREATE OR REPLACE TEMP TABLE company_family_map (cik VARCHAR, company_family VARCHAR)"
        )
        cik_records = staging.execute(
            f"SELECT DISTINCT source_cik FROM ({union_sql}) WHERE source_cik IS NOT NULL"
        )
        if cik_records:
            family_tuples = [
                [r[0], family_index.resolve(r[0]).family_key] for r in cik_records
            ]
            staging.executemany(
                "INSERT INTO company_family_map VALUES (?, ?)", family_tuples
            )

        prof_cols = set(parquet_column_names(self.profile_path))
        if "classification" in prof_cols:
            profiles_sql = (
                f"SELECT cik AS profile_cik, classification.sic_code AS sic_code, "
                f"classification.sic_description AS sic_description, classification.owner_org AS owner_org_cik, "
                f"CAST(NULL AS VARCHAR) AS owner_org_name, COALESCE(classification.entity_type, 'operating') AS entity_type, "
                f"COALESCE(classification.filer_category, 'unspecified') AS filer_category_primary, "
                f"incorporation.state AS state_of_incorporation, CAST(NULL AS VARCHAR) AS state_of_business, "
                f"CAST(NULL AS VARCHAR) AS foreign_country_code, 'domestic' AS foreign_status, "
                f"CASE WHEN classification.owner_org IS NOT NULL THEN 'has_org' ELSE 'no_org' END AS owner_org_presence, "
                f"COALESCE(identity.name, '') AS company_name FROM read_parquet('{self.profile_path}')"
            )
        else:
            profiles_sql = (
                f"SELECT cik AS profile_cik, sic AS sic_code, sic_description, owner_org_cik, owner_org_name, "
                f"entity_type, filer_category, state_of_incorporation, state_of_business, foreign_country_code, "
                f"CASE WHEN foreign_country_code IS NOT NULL THEN 'foreign' ELSE 'domestic' END AS foreign_status, "
                f"CASE WHEN owner_org_cik IS NOT NULL THEN 'has_org' ELSE 'no_org' END AS owner_org_presence, "
                f"COALESCE(filer_category, 'unspecified') AS filer_category_primary, company_name "
                f"FROM read_parquet('{self.profile_path}')"
            )
        era_expr = self._sql_era_of("f.report_date")
        family_expr = self._sql_form_family("f.form")
        query = f"""
            WITH source_filings AS ({union_sql}),
            profiles AS ({profiles_sql})
            SELECT
                f.occurrence_id, f.document_locator_key, f.source_cik, f.accession,
                f.form, {family_expr} AS form_family, f.is_amendment, f.filing_date, f.report_date,
                CASE WHEN f.report_date IS NOT NULL AND length(f.report_date) >= 4 THEN CAST(substring(f.report_date, 1, 4) AS INTEGER) ELSE NULL END AS report_year,
                CASE WHEN f.filing_date IS NOT NULL AND length(f.filing_date) >= 4 THEN CAST(substring(f.filing_date, 1, 4) AS INTEGER) ELSE NULL END AS filing_year,
                {era_expr} AS era,
                CASE WHEN f.primary_document LIKE '%.htm%' THEN 'htm' WHEN f.primary_document LIKE '%.txt%' THEN 'txt' WHEN f.primary_document LIKE '%.pdf%' THEN 'pdf' ELSE 'other' END AS suffix,
                f.primary_document, f.document_path, f.archive_url, f.reported_size,
                f.is_xbrl, f.is_inline_xbrl, f.is_xbrl_numeric,
                CASE WHEN f.reported_size IS NOT NULL AND f.reported_size < {stub_threshold} THEN 'true' ELSE 'false' END AS stub_suspect,
                CASE WHEN f.is_inline_xbrl THEN 'inline_xbrl' WHEN f.is_xbrl THEN 'xbrl_only' ELSE 'no_xbrl' END AS xbrl_state,
                p.sic_code, p.sic_description, p.owner_org_cik, p.owner_org_name, p.owner_org_presence,
                p.foreign_status, p.foreign_country_code, p.entity_type, p.filer_category_primary, p.company_name,
                COALESCE(cf.company_family, p.company_name, '') AS company_family
            FROM source_filings f
            LEFT JOIN profiles p ON f.source_cik = p.profile_cik
            LEFT JOIN company_family_map cf ON p.profile_cik = cf.cik
        """
        return staging.copy_query(query, dest)

    def _write_lifecycle(
        self, staging: DuckDBStaging, union_sql: str, snapshot_dir: Path
    ) -> int:
        dest = snapshot_dir / "lifecycle.parquet"
        gap_years = int(self.options["gap_years"])
        grace_years = int(self.options["cessation_grace_years"])
        query = f"""
            WITH source_filings AS ({union_sql}),
            dated AS (
                SELECT source_cik, CAST(substring(report_date, 1, 4) AS INTEGER) AS year
                FROM source_filings WHERE report_date IS NOT NULL AND length(report_date) >= 4
            ),
            max_year_overall AS (SELECT MAX(year) AS global_max FROM dated),
            distinct_years AS (SELECT DISTINCT source_cik, year FROM dated),
            year_pairs AS (
                SELECT source_cik, year, LEAD(year) OVER (PARTITION BY source_cik ORDER BY year) AS next_year
                FROM distinct_years
            ),
            cik_metrics AS (
                SELECT
                    source_cik, MIN(year) AS min_year, MAX(year) AS max_year, COUNT(DISTINCT year) AS active_years,
                    BOOL_OR(next_year IS NOT NULL AND (next_year - year) >= {gap_years}) AS has_gap
                FROM year_pairs GROUP BY source_cik
            )
            SELECT
                m.source_cik, m.min_year AS first_report_year, m.max_year AS last_report_year, m.active_years,
                COALESCE(m.has_gap, false) AS has_revival_gap,
                CASE
                    WHEN m.active_years <= 2 AND m.max_year >= (g.global_max - 2) THEN 'short_recent_history'
                    WHEN (g.global_max - m.max_year) >= {grace_years} THEN 'ceased_filing_observed'
                    WHEN (g.global_max - m.max_year) <= 1 THEN 'right_censored_active'
                    ELSE 'intermediate_or_dormant'
                END AS lifecycle_class
            FROM cik_metrics m CROSS JOIN max_year_overall g
        """
        return staging.copy_query(query, dest)

    def _write_size_bands(
        self, staging: DuckDBStaging, union_sql: str, snapshot_dir: Path
    ) -> int:
        dest = snapshot_dir / "size_bands.parquet"
        family_expr = self._sql_form_family("form")
        era_expr = self._sql_era_of("report_date")
        query = f"""
            WITH source_filings AS ({union_sql}),
            with_era AS (
                SELECT occurrence_id, reported_size, {family_expr} AS family, {era_expr} AS era
                FROM source_filings WHERE reported_size IS NOT NULL
            ),
            quantiles AS (
                SELECT occurrence_id, NTILE(5) OVER (PARTITION BY family, era ORDER BY reported_size) AS q_val
                FROM with_era
            )
            SELECT
                occurrence_id,
                CASE q_val
                    WHEN 1 THEN 'very_small' WHEN 2 THEN 'small' WHEN 3 THEN 'median' WHEN 4 THEN 'large' WHEN 5 THEN 'very_large'
                    ELSE 'unknown'
                END AS size_band
            FROM quantiles
        """
        return staging.copy_query(query, dest)

    def _write_cross_form(
        self,
        staging: DuckDBStaging,
        union_sql: str,
        forms: list[str],
        snapshot_dir: Path,
    ) -> int:
        dest = snapshot_dir / "cross_form.parquet"
        anchor_set = set(self.policy.anchor_forms)
        comp_set = set(self.policy.comparison_forms)
        if not anchor_set or not comp_set:
            return staging.copy_query(
                "SELECT CAST(NULL AS VARCHAR) AS source_cik, 'unspecified' AS anchor_status, 'unspecified' AS comparison_status WHERE 1 = 0",
                dest,
            )

        anchor_list = ", ".join(f"'{f}'" for f in sorted(anchor_set))
        comp_list = ", ".join(f"'{f}'" for f in sorted(comp_set))
        query = f"""
            WITH source_filings AS ({union_sql}),
            dated AS (
                SELECT source_cik, form, CAST(substring(report_date, 1, 4) AS INTEGER) AS year
                FROM source_filings WHERE report_date IS NOT NULL AND length(report_date) >= 4
            ),
            anchor_dates AS (
                SELECT source_cik, MAX(year) AS last_anchor_year
                FROM dated WHERE form IN ({anchor_list}) GROUP BY source_cik
            ),
            comparison_dates AS (
                SELECT source_cik, MAX(year) AS last_comp_year
                FROM dated WHERE form IN ({comp_list}) GROUP BY source_cik
            ),
            global_max AS (SELECT MAX(year) AS global_max_year FROM dated)
            SELECT
                c.source_cik,
                CASE
                    WHEN a.last_anchor_year IS NULL THEN 'no_anchor'
                    WHEN (g.global_max_year - a.last_anchor_year) >= 5 THEN 'anchor_ceased_observed'
                    ELSE 'anchor_active'
                END AS anchor_status,
                CASE
                    WHEN k.last_comp_year IS NULL THEN 'no_comparison'
                    WHEN a.last_anchor_year IS NOT NULL AND k.last_comp_year > a.last_anchor_year THEN 'comparison_active_after_anchor'
                    ELSE 'comparison_aligned_or_earlier'
                END AS comparison_status
            FROM (SELECT DISTINCT source_cik FROM dated) c
            LEFT JOIN anchor_dates a ON c.source_cik = a.source_cik
            LEFT JOIN comparison_dates k ON c.source_cik = k.source_cik
            CROSS JOIN global_max g
        """
        return staging.copy_query(query, dest)

    def _write_occurrence_features(
        self, staging: DuckDBStaging, snapshot_dir: Path
    ) -> int:
        dest = snapshot_dir / "occurrence_features.parquet"
        base = snapshot_dir / "occurrence_base.parquet"
        lifecycle = snapshot_dir / "lifecycle.parquet"
        size_bands = snapshot_dir / "size_bands.parquet"
        cross_form = snapshot_dir / "cross_form.parquet"
        query = f"""
            WITH occurrences AS (SELECT * FROM read_parquet('{base}')),
            occ_per_locator AS (SELECT document_locator_key, COUNT(*) AS loc_occ_count FROM occurrences GROUP BY document_locator_key),
            occ_per_accession AS (SELECT accession, COUNT(*) AS acc_occ_count FROM occurrences GROUP BY accession)
            SELECT
                o.*,
                COALESCE(s.size_band, 'unknown') AS size_band,
                COALESCE(l.first_report_year, o.report_year) AS first_report_year,
                COALESCE(l.last_report_year, o.report_year) AS last_report_year,
                COALESCE(l.active_years, 1) AS active_years,
                COALESCE(l.has_revival_gap, false) AS has_revival_gap,
                COALESCE(l.lifecycle_class, 'unknown') AS lifecycle_class,
                COALESCE(c.anchor_status, 'unspecified') AS anchor_status,
                COALESCE(c.comparison_status, 'unspecified') AS comparison_status,
                CASE WHEN la.acc_occ_count = 1 THEN 'single' WHEN la.acc_occ_count BETWEEN 2 AND 3 THEN 'low_2_to_3' ELSE 'high_4_plus' END AS accession_class,
                CASE WHEN ll.loc_occ_count = 1 THEN 'single' WHEN ll.loc_occ_count BETWEEN 2 AND 3 THEN 'low_2_to_3' ELSE 'high_4_plus' END AS locator_class
            FROM occurrences o
            LEFT JOIN read_parquet('{size_bands}') s ON o.occurrence_id = s.occurrence_id
            LEFT JOIN read_parquet('{lifecycle}') l ON o.source_cik = l.source_cik
            LEFT JOIN read_parquet('{cross_form}') c ON o.source_cik = c.source_cik
            LEFT JOIN occ_per_locator ll ON o.document_locator_key = ll.document_locator_key
            LEFT JOIN occ_per_accession la ON o.accession = la.accession
        """
        return staging.copy_query(query, dest)

    def _write_locator_features(
        self, staging: DuckDBStaging, snapshot_dir: Path
    ) -> int:
        dest = snapshot_dir / "locator_features.parquet"
        occ = snapshot_dir / "occurrence_features.parquet"
        query = f"""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY document_locator_key ORDER BY occurrence_id) AS rn
                FROM read_parquet('{occ}')
            )
            SELECT
                document_locator_key, form, form_family, era, suffix, xbrl_state, size_band,
                owner_org_presence, foreign_status, foreign_country_code, entity_type, filer_category_primary,
                lifecycle_class, has_revival_gap, locator_class, stub_suspect, anchor_status, comparison_status,
                is_amendment, reported_size, report_year, filing_year, filing_date, report_date, primary_document,
                document_path, archive_url, source_cik AS representative_cik, accession AS representative_accession,
                sic_code, company_name, company_family
            FROM ranked WHERE rn = 1
        """
        return staging.copy_query(query, dest)


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "FeatureSnapshotBuilder",
    "SnapshotPaths",
    "era_of",
    "form_family",
]
