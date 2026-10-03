"""Bounded, storage-backed candidate access: the selector never holds the pool. Every
query returns at most `limit` rows, so a corpus larger than memory stays selectable;
filter values are bound parameters and dimension names are validated.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import (
    DateSelection,
)
from edgar_sec.engine.selection.policy import KNOWN_DIMENSIONS
from edgar_sec.engine.selection.predicates import (
    date_selection_sql,
    parsed_date_relation,
    suffix_sql,
)
from edgar_sec.infra.storage.duckdb import connect, sql_literal

# A tuple, not a comma-joined string, so the SELECT list and the row-to-dict
# zip are generated from one source.
POOL_COLUMNS: tuple[str, ...] = (
    "document_locator_key",
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
    "anchor_status",
    "comparison_status",
    "company_name",
    "company_family",
    "reported_size",
    "report_year",
    "representative_cik",
)

# Returned for the active selection, so a consumer need not re-read the snapshot.
OCCURRENCE_COLUMNS: tuple[str, ...] = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "reported_size",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
    "sic_code",
    "sic_description",
    "owner_org_cik",
    "owner_org_presence",
    "foreign_status",
    "foreign_country_code",
    "state_of_incorporation",
    "state_of_business",
    "entity_type",
    "filer_category_primary",
    "company_name",
)

_POOL_SELECT = ", ".join(POOL_COLUMNS)
_OCCURRENCE_SELECT = ", ".join(OCCURRENCE_COLUMNS)
_QUALIFIED_POOL_SELECT = ", ".join(f"l.{c}" for c in POOL_COLUMNS)
_QUALIFIED_OCCURRENCE_SELECT = ", ".join(f"o.{c}" for c in OCCURRENCE_COLUMNS)
_INSERT_BATCH = 5_000

# The seed must sit *inside* the concatenation: DuckDB constant-folds
# `constant || column`, so a seed beside the key sorts every row equal and the pool
# comes back in file order — deterministic, but not seed-dependent at all.
_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || l.document_locator_key)"
_RANKED_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || ranked.document_locator_key)"

_SELECTED_TABLE = "selected_keys"
_LOCATOR_KEYS_TABLE = "requested_locator_keys"
_CIK_TABLE = "requested_ciks"


class SelectionSessionError(RuntimeError):
    """A candidate query was attempted outside an open session."""


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    """The policy-level filters applied to every pool query; built once so the
    predicate cannot drift between pools.
    """

    document_suffixes: tuple[str, ...] = ()
    max_reported_size: int | None = None
    date_selection: DateSelection = ()

    def filters_dates(self) -> bool:
        return bool(self.date_selection)

    def predicate(self) -> str:
        clauses: list[str] = []
        if self.max_reported_size is not None:
            clauses.append(f"l.reported_size <= {int(self.max_reported_size)}")
        if self.document_suffixes:
            # Suffixes apply to the effective document path: the primary
            # document for an observed row, the synthetic bundle path for a
            # fallback locator.
            clauses.append(suffix_sql("l.document_path", self.document_suffixes))
        if self.date_selection:
            # Applied here, not after selection, so an out-of-range locator
            # cannot be drawn by any phase and consume quota on the way there.
            clauses.append(date_selection_sql(self.date_selection))
        return " AND ".join(clauses) if clauses else "TRUE"


class CandidateSource:
    """Deterministic, storage-backed access to locator and occurrence rows."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        seed: str,
        *,
        page_size: int = 5_000,
        filters: CandidateFilters | None = None,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.locator = self.snapshot_dir / "locator_features.parquet"
        self.occurrence = self.snapshot_dir / "occurrence_features.parquet"
        for required in (self.locator, self.occurrence):
            if not required.is_file():
                raise FileNotFoundError(f"feature snapshot is missing {required}")
        self.seed = seed
        self.page_size = page_size
        self.filters = filters or CandidateFilters()
        self._threads = threads
        self._memory_limit = memory_limit
        self._con: Any | None = None

    # -------------------------------------------------------------- session

    @contextmanager
    def session(self) -> Iterator[CandidateSource]:
        """Open the candidate session and its working tables. The connection is in-memory,
        so a session leaves no mutable state in the snapshot directory.
        """
        con = connect(threads=self._threads, memory_limit=self._memory_limit)
        try:
            for table in (_SELECTED_TABLE, _LOCATOR_KEYS_TABLE, _CIK_TABLE):
                con.execute(
                    f"CREATE OR REPLACE TEMP TABLE {table} "
                    "(document_locator_key VARCHAR)"
                )
            self._con = con
            yield self
        finally:
            self._con = None
            con.close()

    def _require(self) -> Any:
        if self._con is None:
            raise SelectionSessionError("CandidateSource session is not open")
        return self._con

    def _fill(self, table: str, values: Sequence[str]) -> None:
        con = self._require()
        con.execute(f"DELETE FROM {table}")
        for start in range(0, len(values), _INSERT_BATCH):
            chunk = [[value] for value in values[start : start + _INSERT_BATCH]]
            con.executemany(f"INSERT INTO {table} VALUES (?)", chunk)

    def _exclusion_predicate(self) -> str:
        return f"l.document_locator_key NOT IN (SELECT document_locator_key FROM {_SELECTED_TABLE})"

    def _locator_source(self) -> str:
        """The locator relation, projected so a date predicate sees one column; wrapping
        here keeps the outer alias `l` for every qualified reference in this module.
        """
        relation = f"read_parquet({sql_literal(str(self.locator))})"
        if self.filters.filters_dates():
            return f"{parsed_date_relation(relation, 'report_date')} l"
        return f"{relation} l"

    def _rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        rows = self._require().execute(query, list(params)).fetchall()
        return [dict(zip(POOL_COLUMNS, row, strict=True)) for row in rows]

    @staticmethod
    def _dimension(dimension: str) -> str:
        if dimension not in KNOWN_DIMENSIONS:
            raise ValueError(f"unknown selection dimension: {dimension!r}")
        return dimension

    # ------------------------------------------------------------ selection

    def register_selected(self, keys: Sequence[str]) -> None:
        self._fill(_SELECTED_TABLE, keys)

    def add_selected(self, key: str) -> None:
        """Record one newly selected locator in the exclusion set."""
        self._require().execute(f"INSERT INTO {_SELECTED_TABLE} VALUES (?)", [key])

    # ---------------------------------------------------------------- pools

    def pool_for_value(
        self, dimension: str, value: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        column = self._dimension(dimension)
        query = f"""
            SELECT {_POOL_SELECT}
            FROM {self._locator_source()}
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
              AND l.{column} = ?
            ORDER BY {_ORDER_EXPR}
            LIMIT {int(limit)}
        """
        return self._rows(query, [value, self.seed])

    def pool_for_cell(
        self, form: str, era: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Candidates in one form-by-era cell, in the shared tie-break order. Two columns
        of one row are one stratum, which a floor on `form` alone cannot express.
        """
        query = f"""
            SELECT {_POOL_SELECT}
            FROM {self._locator_source()}
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
              AND l.form = ? AND l.era = ?
            ORDER BY {_ORDER_EXPR}
            LIMIT {int(limit)}
        """
        return self._rows(query, [form, era, self.seed])

    def cell_availability(self) -> list[tuple[str, str, int]]:
        """Every nonempty `(form, era)` cell with its eligible count, excluding the selected
        set: a cell with nothing left is not capacity.
        """
        rows = (
            self._require()
            .execute(
                f"""
            SELECT l.form, l.era, COUNT(*) AS available
            FROM {self._locator_source()}
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
            GROUP BY l.form, l.era
            ORDER BY l.form, l.era
            """
            )
            .fetchall()
        )
        return [(str(form), str(era), int(count)) for form, era, count in rows]

    def pool_for_composite(
        self, filters: dict[str, Any], limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return candidates satisfying every filter of one composite stratum."""
        clauses = [self._exclusion_predicate(), self.filters.predicate()]
        clauses.extend(f"l.{self._dimension(dimension)} = ?" for dimension in filters)
        query = f"""
            SELECT {_POOL_SELECT}
            FROM {self._locator_source()}
            WHERE {" AND ".join(clauses)}
            ORDER BY {_ORDER_EXPR}
            LIMIT {int(limit)}
        """
        params = [str(value) for value in filters.values()] + [self.seed]
        return self._rows(query, params)

    def pool_for_ciks(
        self, ciks: Sequence[str], limit_per_cik: int = 5
    ) -> list[dict[str, Any]]:
        """Up to `limit_per_cik` candidates per supplied CIK. The cap is per CIK, not
        global, or one mandatory seed registrant could consume the whole budget.
        """
        if not ciks:
            return []
        self._fill(_CIK_TABLE, ciks)
        # The inner rank is per CIK; the outer order is the same global
        # tie-break, so the page a CIK pool draws from is seed-deterministic.
        query = f"""
            WITH ranked AS (
                SELECT {_POOL_SELECT},
                       ROW_NUMBER() OVER (
                           PARTITION BY l.representative_cik
                           ORDER BY {_ORDER_EXPR}
                       ) AS cik_rank
                FROM {self._locator_source()}
                WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
                  AND l.representative_cik IN (
                      SELECT document_locator_key FROM {_CIK_TABLE}
                  )
            )
            SELECT {_POOL_SELECT}
            FROM ranked
            WHERE cik_rank <= {int(limit_per_cik)}
            ORDER BY {_RANKED_ORDER_EXPR}
        """
        return self._rows(query, [self.seed, self.seed])

    def candidate_page(self, page_index: int) -> list[dict[str, Any]]:
        """One deterministic page of unselected candidates: `OFFSET` over a seed-derived
        total order, so a page index yields the same rows for the same snapshot.
        """
        query = f"""
            SELECT {_POOL_SELECT}
            FROM {self._locator_source()}
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
            ORDER BY {_ORDER_EXPR}
            LIMIT {int(self.page_size)} OFFSET {int(page_index) * self.page_size}
        """
        return self._rows(query, [self.seed])

    # ------------------------------------------------------------- retrieval

    def load_candidates_for_locators(
        self, locator_keys: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Feature rows of an existing selection, in the caller's order, so a parent
        selection's coverage accounting lines up with its keys.
        """
        if not locator_keys:
            return []
        self._fill(_LOCATOR_KEYS_TABLE, locator_keys)
        rows = self._rows(
            f"""
            SELECT {_QUALIFIED_POOL_SELECT}
            FROM read_parquet({sql_literal(str(self.locator))}) l
            JOIN {_LOCATOR_KEYS_TABLE} r
              ON l.document_locator_key = r.document_locator_key
            """
        )
        by_key = {str(row["document_locator_key"]): row for row in rows}
        missing = [key for key in locator_keys if key not in by_key]
        if missing:
            raise ValueError(
                "parent plan references locator keys absent from the selection "
                "snapshot: " + ", ".join(missing[:5])
            )
        return [by_key[key] for key in locator_keys]

    def load_occurrences_for_locators(
        self, locator_keys: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Every occurrence belonging to the selected locators; a locator with two
        co-filers yields two rows, one per registrant's claim on one document.
        """
        if not locator_keys:
            return []
        con = self._require()
        self._fill(_LOCATOR_KEYS_TABLE, locator_keys)
        rows = con.execute(
            f"""
            SELECT {_QUALIFIED_OCCURRENCE_SELECT}
            FROM read_parquet({sql_literal(str(self.occurrence))}) o
            JOIN {_LOCATOR_KEYS_TABLE} r
              ON o.document_locator_key = r.document_locator_key
            ORDER BY o.document_locator_key, o.occurrence_id
            """,
            [],
        ).fetchall()
        return [dict(zip(OCCURRENCE_COLUMNS, row, strict=True)) for row in rows]


__all__ = [
    "OCCURRENCE_COLUMNS",
    "POOL_COLUMNS",
    "CandidateFilters",
    "CandidateSource",
    "SelectionSessionError",
]
