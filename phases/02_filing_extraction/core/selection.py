"""Deterministic round-robin deficit selection over a feature snapshot.

Policy-driven and stateful: hard floors and composite strata are satisfied
first by rotating through the most deficient dimension values, then remaining
slots are filled by weighted marginal coverage. Every tie is broken by
md5(seed || locator_key) for strict reproducibility.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defs.runtime.resources import derive_resources
from defs.storage import DuckDBStaging

from .selection_policy import (
    KNOWN_DIMENSIONS,
    SeedFiler,
    SelectionPolicy,
    normalize_value,
)

POOL_COLUMNS = (
    "document_locator_key, form, form_family, era, suffix, xbrl_state, "
    "size_band, sic_code, owner_org_presence, foreign_status, foreign_country_code, "
    "entity_type, filer_category_primary, lifecycle_class, has_revival_gap, "
    "locator_class, stub_suspect, anchor_status, comparison_status, company_name, "
    "company_family, reported_size, report_year, is_amendment"
)


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _stable_hash(seed: str, key: str) -> str:
    return hashlib.md5(f"{seed}{key}".encode()).hexdigest()


class CandidateSource:
    """Storage-backed candidate access with bounded memory behavior."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        seed: str,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
        page_size: int = 5_000,
        max_reported_size: int | None = None,
        exclude_amendments: bool = False,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.locator = str(self.snapshot_dir / "locator_features.parquet")
        self.occurrence = str(self.snapshot_dir / "occurrence_features.parquet")
        self.seed = seed
        res = derive_resources()
        self.threads = threads if threads is not None else res.threads
        self.memory_limit = memory_limit or res.memory_limit
        self.page_size = page_size
        self.max_reported_size = max_reported_size
        self.exclude_amendments = exclude_amendments
        self._staging: DuckDBStaging | None = None

    @contextmanager
    def session(self) -> Iterator[None]:
        """Open the selection session; cleans up temporary staging on exit."""
        db_file = self.snapshot_dir / "selection_session.duckdb"
        try:
            self._staging = DuckDBStaging(
                db_file,
                threads=self.threads,
                memory_limit=self.memory_limit,
                cleanup_root=False,
            )
            self._staging.execute(
                "CREATE OR REPLACE TEMP TABLE selected_keys "
                "(document_locator_key VARCHAR)"
            )
            yield
        finally:
            if self._staging is not None:
                self._staging.close()
                self._staging = None

    def _require(self) -> DuckDBStaging:
        if self._staging is None:
            raise RuntimeError("CandidateSource session is not open")
        return self._staging

    def register_selected(self, keys: list[str]) -> None:
        """Replace the selected-key temp table with the supplied keys."""
        staging = self._require()
        staging.execute("DELETE FROM selected_keys")
        self._insert_keys(keys)

    def add_selected(self, key: str) -> None:
        """Record one newly selected locator key in the exclusion table."""
        self._require().execute("INSERT INTO selected_keys VALUES (?)", [key])

    def _insert_keys(self, keys: list[str]) -> None:
        staging = self._require()
        step = 5_000
        for idx in range(0, len(keys), step):
            chunk = [[k] for k in keys[idx : idx + step]]
            staging.executemany("INSERT INTO selected_keys VALUES (?)", chunk)

    def _base_filter(self) -> str:
        clauses = [
            "l.document_locator_key NOT IN (SELECT document_locator_key FROM selected_keys)"
        ]
        if self.max_reported_size is not None:
            clauses.append(f"l.reported_size <= {int(self.max_reported_size)}")
        if self.exclude_amendments:
            clauses.append("l.is_amendment = false")
        return " AND ".join(clauses)

    def pool_for_value(
        self, dimension: str, value: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return candidate rows satisfying dimension = value."""
        staging = self._require()
        where = f"{self._base_filter()} AND l.{dimension} = {_sql_quote(value)}"
        query = f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {where}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(limit)}
        """
        rows = staging.execute(query)
        cols = [c.strip() for c in POOL_COLUMNS.split(",") if c.strip()]
        return [dict(zip(cols, row)) for row in rows]

    def pool_for_composite(
        self, filters: dict[str, Any], limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return candidates satisfying all filters in the composite."""
        staging = self._require()
        clauses = [self._base_filter()]
        for dim, val in filters.items():
            clauses.append(f"l.{dim} = {_sql_quote(str(val))}")
        where = " AND ".join(clauses)
        query = f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {where}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(limit)}
        """
        rows = staging.execute(query)
        cols = [c.strip() for c in POOL_COLUMNS.split(",") if c.strip()]
        return [dict(zip(cols, row)) for row in rows]

    def pool_for_ciks(
        self, ciks: list[str], limit_per_cik: int = 5
    ) -> list[dict[str, Any]]:
        """Return candidates belonging to the supplied CIKs."""
        if not ciks:
            return []
        staging = self._require()
        cik_list = ", ".join(_sql_quote(c) for c in ciks)
        where = f"{self._base_filter()} AND l.representative_cik IN ({cik_list})"
        query = f"""
            WITH ranked AS (
                SELECT {POOL_COLUMNS},
                       ROW_NUMBER() OVER (
                           PARTITION BY l.representative_cik
                           ORDER BY md5('{self.seed}' || l.document_locator_key)
                       ) AS cik_rn
                FROM read_parquet('{self.locator}') l
                WHERE {where}
            )
            SELECT {POOL_COLUMNS}
            FROM ranked
            WHERE cik_rn <= {int(limit_per_cik)}
            ORDER BY md5('{self.seed}' || document_locator_key)
        """
        rows = staging.execute(query)
        cols = [c.strip() for c in POOL_COLUMNS.split(",") if c.strip()]
        return [dict(zip(cols, row)) for row in rows]

    def candidate_page(self, page_index: int) -> list[dict[str, Any]]:
        """Return one deterministic page of candidates."""
        staging = self._require()
        offset = page_index * self.page_size
        query = f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {self._base_filter()}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(self.page_size)} OFFSET {int(offset)}
        """
        rows = staging.execute(query)
        cols = [c.strip() for c in POOL_COLUMNS.split(",") if c.strip()]
        return [dict(zip(cols, row)) for row in rows]

    def load_occurrences_for_locators(
        self, locator_keys: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch all occurrences mapping to the selected locator keys."""
        if not locator_keys:
            return []
        staging = self._require()
        step = 5_000
        occurrences = []
        for idx in range(0, len(locator_keys), step):
            subset = locator_keys[idx : idx + step]
            key_list = ", ".join(_sql_quote(k) for k in subset)
            query = f"""
                SELECT
                    occurrence_id, document_locator_key, source_cik, accession,
                    form, is_amendment, filing_date, report_date, primary_document,
                    document_path, archive_url, reported_size, is_xbrl,
                    is_inline_xbrl, is_xbrl_numeric, sic_code, sic_description,
                    owner_org_cik, owner_org_name, owner_org_presence,
                    foreign_status, foreign_country_code, entity_type,
                    filer_category_primary, company_name
                FROM read_parquet('{self.occurrence}')
                WHERE document_locator_key IN ({key_list})
                ORDER BY document_locator_key, occurrence_id
            """
            rows = staging.execute(query)
            cols = [
                "occurrence_id",
                "document_locator_key",
                "source_cik",
                "accession",
                "form",
                "is_amendment",
                "filing_date",
                "report_date",
                "primary_document",
                "document_path",
                "archive_url",
                "reported_size",
                "is_xbrl",
                "is_inline_xbrl",
                "is_xbrl_numeric",
                "sic_code",
                "sic_description",
                "owner_org_cik",
                "owner_org_name",
                "owner_org_presence",
                "foreign_status",
                "foreign_country_code",
                "entity_type",
                "filer_category_primary",
                "company_name",
            ]
            occurrences.extend(dict(zip(cols, r)) for r in rows)
        return occurrences


@dataclass
class SelectionResult:
    active_locators: list[str]
    active_candidates: list[dict[str, Any]]
    active_occurrences: list[dict[str, Any]]
    reserve_locators: list[str]
    reserve_candidates: list[dict[str, Any]]
    report: dict[str, Any]


class DeficitSelector:
    """Execute policy-driven deficit selection over snapshot."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        policy: SelectionPolicy,
        seed_filers: dict[str, SeedFiler] | None = None,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.policy = policy
        self.seed_filers = seed_filers or {}
        res = derive_resources()
        self.threads = threads if threads is not None else res.threads
        self.memory_limit = memory_limit or res.memory_limit

    def select(self, parent_active_keys: list[str] | None = None) -> SelectionResult:
        """Run full deficit selection and produce typed SelectionResult."""
        target_units = self.policy.requested_units()
        source = CandidateSource(
            snapshot_dir=self.snapshot_dir,
            seed=self.policy.seed,
            threads=self.threads,
            memory_limit=self.memory_limit,
            page_size=self.policy.page_size,
            max_reported_size=self.policy.max_reported_size,
            exclude_amendments=self.policy.exclude_amendments,
        )

        selected_keys: list[str] = list(parent_active_keys or [])
        selected_candidates: list[dict[str, Any]] = []
        coverage: dict[str, dict[str, int]] = {dim: {} for dim in KNOWN_DIMENSIONS}
        company_classification_counts: Counter[tuple[str, ...]] = Counter()
        deduplicated_company_classifications = 0

        def _classification_signature(cand: dict[str, Any]) -> tuple[str, ...]:
            return (
                normalize_value(cand.get("company_family") or cand.get("company_name")),
                normalize_value(cand.get("form")),
                normalize_value(cand.get("era")),
                normalize_value(cand.get("sic_code")),
                normalize_value(cand.get("entity_type")),
                normalize_value(cand.get("lifecycle_class")),
            )

        def _record(cand: dict[str, Any], *, check_dedup: bool = True) -> bool:
            nonlocal deduplicated_company_classifications
            k = str(cand["document_locator_key"])
            if k in selected_set:
                return False

            sig = _classification_signature(cand)
            if (
                check_dedup
                and self.policy.max_per_company_classification is not None
                and (
                    company_classification_counts[sig]
                    >= self.policy.max_per_company_classification
                )
            ):
                deduplicated_company_classifications += 1
                return False

            selected_set.add(k)
            selected_keys.append(k)
            selected_candidates.append(cand)
            company_classification_counts[sig] += 1
            source.add_selected(k)
            for dim in KNOWN_DIMENSIONS:
                val = normalize_value(cand.get(dim))
                coverage[dim][val] = coverage[dim].get(val, 0) + 1
            return True

        with source.session():
            selected_set = set(selected_keys)
            source.register_selected(selected_keys)

            # Phase 1: Seed Filers
            if self.seed_filers:
                seed_ciks = list(self.seed_filers.keys())
                for cand in source.pool_for_ciks(seed_ciks, limit_per_cik=5):
                    if len(selected_keys) >= target_units:
                        break
                    _record(cand, check_dedup=False)

            # Phase 2: Composite Strata
            for comp in self.policy.composites:
                filters = comp.get("filters", {})
                req = int(comp.get("min", 1))
                pool = source.pool_for_composite(filters, limit=max(req * 2, 60))
                comp_added = 0
                for cand in pool:
                    if comp_added >= req or len(selected_keys) >= target_units:
                        break
                    if _record(cand):
                        comp_added += 1

            # Phase 3: Single-Dimension Floors
            rounds = 0
            while (
                rounds < self.policy.max_pool_rounds
                and len(selected_keys) < target_units
            ):
                rounds += 1
                deficits: list[tuple[float, str, str, int]] = []
                for dim, reqs in self.policy.floors.items():
                    for val, req in reqs.items():
                        norm_val = normalize_value(val)
                        curr = coverage[dim].get(norm_val, 0)
                        if curr < req:
                            deficit_ratio = (req - curr) / req
                            deficits.append((deficit_ratio, dim, val, req - curr))

                if not deficits:
                    break

                deficits.sort(key=lambda x: -x[0])
                progress_made = False
                for _, dim, val, need in deficits:
                    if len(selected_keys) >= target_units:
                        break
                    pool = source.pool_for_value(
                        dim, val, limit=min(need * 2, self.policy.pool_per_value)
                    )
                    for cand in pool:
                        if _record(cand):
                            progress_made = True
                            break
                if not progress_made:
                    break

            # Phase 4: Weighted Pool Filling
            page_idx = 0
            while (
                len(selected_keys) < target_units and page_idx < self.policy.max_pages
            ):
                page = source.candidate_page(page_idx)
                if not page:
                    break
                page_idx += 1
                for cand in page:
                    if len(selected_keys) >= target_units:
                        break
                    # Check caps
                    violates_cap = False
                    for dim, cap in self.policy.caps.items():
                        val = normalize_value(cand.get(dim))
                        curr = coverage[dim].get(val, 0)
                        if (curr + 1) / target_units > cap:
                            violates_cap = True
                            break
                    if not violates_cap:
                        _record(cand)

            # Phase 5: Reserve Selection
            reserve_keys: list[str] = []
            reserve_candidates: list[dict[str, Any]] = []
            if self.policy.reserve_size > 0:
                res_page_idx = 0
                while (
                    len(reserve_keys) < self.policy.reserve_size and res_page_idx < 100
                ):
                    page = source.candidate_page(res_page_idx)
                    if not page:
                        break
                    res_page_idx += 1
                    for cand in page:
                        if len(reserve_keys) >= self.policy.reserve_size:
                            break
                        k = str(cand["document_locator_key"])
                        if k not in selected_set and k not in reserve_keys:
                            reserve_keys.append(k)
                            reserve_candidates.append(cand)
                            source.add_selected(k)

            # Materialize Active Occurrences
            active_occurrences = source.load_occurrences_for_locators(selected_keys)

        # Build Coverage & Validation Report
        underfilled_floors: dict[str, dict[str, dict[str, int]]] = {}
        for dim, reqs in self.policy.floors.items():
            for val, req in reqs.items():
                norm_val = normalize_value(val)
                actual = coverage[dim].get(norm_val, 0)
                if actual < req:
                    underfilled_floors.setdefault(dim, {})[val] = {
                        "required": req,
                        "selected": actual,
                        "deficit": req - actual,
                    }

        report = {
            "policy_fingerprint": self.policy.policy_fingerprint,
            "corpus_id": self.policy.corpus_id,
            "level": self.policy.level,
            "target_units": target_units,
            "active_locators_count": len(selected_keys),
            "active_occurrences_count": len(active_occurrences),
            "reserve_locators_count": len(reserve_keys),
            "deduplicated_company_classifications": deduplicated_company_classifications,
            "unique_company_families": len(
                {sig[0] for sig in company_classification_counts if sig[0] != "none"}
            ),
            "underfilled_floors": underfilled_floors,
            "coverage_distributions": {
                dim: counts for dim, counts in coverage.items() if counts
            },
        }

        return SelectionResult(
            active_locators=selected_keys,
            active_candidates=selected_candidates,
            active_occurrences=active_occurrences,
            reserve_locators=reserve_keys,
            reserve_candidates=reserve_candidates,
            report=report,
        )


__all__ = [
    "CandidateSource",
    "DeficitSelector",
    "SelectionResult",
    "normalize_value",
]
