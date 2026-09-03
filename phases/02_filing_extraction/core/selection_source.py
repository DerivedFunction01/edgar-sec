"""Storage-backed candidate access for policy-driven target selection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from defs.runtime.resources import derive_resources
from defs.storage import DuckDBStaging

POOL_COLUMNS = (
    "document_locator_key, form, form_family, era, suffix, xbrl_state, "
    "size_band, sic_code, owner_org_presence, foreign_status, foreign_country_code, "
    "entity_type, filer_category_primary, lifecycle_class, has_revival_gap, "
    "locator_class, stub_suspect, anchor_status, comparison_status, company_name, "
    "company_family, reported_size, report_year, is_amendment"
)


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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
            chunk = [[key] for key in keys[idx : idx + step]]
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

    def _rows(self, query: str) -> list[dict[str, Any]]:
        rows = self._require().execute(query)
        columns = [column.strip() for column in POOL_COLUMNS.split(",")]
        return [dict(zip(columns, row)) for row in rows]

    def pool_for_value(
        self, dimension: str, value: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return candidate rows satisfying dimension = value."""
        where = f"{self._base_filter()} AND l.{dimension} = {_sql_quote(value)}"
        return self._rows(
            f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {where}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(limit)}
            """
        )

    def pool_for_composite(
        self, filters: dict[str, Any], limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return candidates satisfying all filters in the composite."""
        clauses = [self._base_filter()]
        clauses.extend(
            f"l.{dimension} = {_sql_quote(str(value))}"
            for dimension, value in filters.items()
        )
        return self._rows(
            f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {" AND ".join(clauses)}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(limit)}
            """
        )

    def pool_for_ciks(
        self, ciks: list[str], limit_per_cik: int = 5
    ) -> list[dict[str, Any]]:
        """Return candidates belonging to the supplied CIKs."""
        if not ciks:
            return []
        cik_list = ", ".join(_sql_quote(cik) for cik in ciks)
        where = f"{self._base_filter()} AND l.representative_cik IN ({cik_list})"
        return self._rows(
            f"""
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
        )

    def candidate_page(self, page_index: int) -> list[dict[str, Any]]:
        """Return one deterministic page of candidates."""
        offset = page_index * self.page_size
        return self._rows(
            f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE {self._base_filter()}
            ORDER BY md5('{self.seed}' || l.document_locator_key)
            LIMIT {int(self.page_size)} OFFSET {int(offset)}
            """
        )

    def load_candidates_for_locators(
        self, locator_keys: list[str]
    ) -> list[dict[str, Any]]:
        """Load feature rows for an existing selection in deterministic order."""
        if not locator_keys:
            return []
        key_list = ", ".join(_sql_quote(key) for key in locator_keys)
        rows = self._rows(
            f"""
            SELECT {POOL_COLUMNS}
            FROM read_parquet('{self.locator}') l
            WHERE l.document_locator_key IN ({key_list})
            """
        )
        by_key = {str(row["document_locator_key"]): row for row in rows}
        missing = [key for key in locator_keys if key not in by_key]
        if missing:
            raise ValueError(
                "parent plan references locator keys absent from the selection snapshot: "
                + ", ".join(missing[:5])
            )
        return [by_key[key] for key in locator_keys]

    def load_occurrences_for_locators(
        self, locator_keys: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch all occurrences mapping to the selected locator keys."""
        if not locator_keys:
            return []
        staging = self._require()
        step = 5_000
        occurrences = []
        columns = [
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
        for idx in range(0, len(locator_keys), step):
            subset = locator_keys[idx : idx + step]
            key_list = ", ".join(_sql_quote(key) for key in subset)
            rows = staging.execute(
                f"""
                SELECT {", ".join(columns)}
                FROM read_parquet('{self.occurrence}')
                WHERE document_locator_key IN ({key_list})
                ORDER BY document_locator_key, occurrence_id
                """
            )
            occurrences.extend(dict(zip(columns, row)) for row in rows)
        return occurrences


__all__ = ["CandidateSource"]
