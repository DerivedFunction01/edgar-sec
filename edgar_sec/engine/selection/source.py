"""Bounded, storage-backed candidate access: the selector never holds the pool. Every
query returns at most `limit` rows, so a corpus larger than memory stays selectable;
filter values are bound parameters and dimension names are validated.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import (
    DateSelection,
)
from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
)
from edgar_sec.engine.selection.policy import KNOWN_DIMENSIONS
from edgar_sec.engine.selection.predicates import (
    date_selection_sql,
    parsed_date_relation,
    suffix_sql,
)
from edgar_sec.engine.selection.snapshot import load_snapshot_paths
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.duckdb import connect

# A tuple, not a comma-joined string, so the SELECT list and the row-to-dict zip
# are generated from one source. Which names each grain selects is curated; their
# spelling and order come from the snapshot schema they are selected out of.
_POOL_SELECTED = frozenset(
    {
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
        "primary_exhibit_like",
        "company_family",
        "reported_size",
        "representative_cik",
        "representative_accession",
    }
)

POOL_COLUMNS: tuple[str, ...] = tuple(
    column for column in LOCATOR_FEATURE_COLUMNS if column in _POOL_SELECTED
)

# Returned for the active selection, so a consumer need not re-read the snapshot.
_OCCURRENCE_SELECTED = frozenset(
    {
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
        "primary_exhibit_like",
        "reported_size",
        "is_xbrl",
        "is_inline_xbrl",
        "is_xbrl_numeric",
        "sic_code",
        "owner_org_presence",
        "foreign_status",
        "foreign_country_code",
        "state_of_incorporation",
        "entity_type",
        "filer_category_primary",
    }
)

OCCURRENCE_COLUMNS: tuple[str, ...] = tuple(
    column for column in OCCURRENCE_FEATURE_COLUMNS if column in _OCCURRENCE_SELECTED
)

_POOL_SELECT = ", ".join(POOL_COLUMNS)
_OCCURRENCE_SELECT = ", ".join(OCCURRENCE_COLUMNS)
_QUALIFIED_POOL_SELECT = ", ".join(f"l.{c}" for c in POOL_COLUMNS)
_QUALIFIED_OCCURRENCE_SELECT = ", ".join(f"o.{c}" for c in OCCURRENCE_COLUMNS)
_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || l.document_locator_key)"
_RANKED_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || ranked.document_locator_key)"

_SELECTED_TABLE = "selected_keys"
_LOCATOR_KEYS_TABLE = "requested_locator_keys"
_CIK_TABLE = "requested_ciks"
_ACCESSION_TABLE = "excluded_accessions"


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
        snapshot = load_snapshot_paths(self.snapshot_dir)
        self.occurrence_relation = snapshot.occurrence_relation
        self.locator_relation = snapshot.locator_relation
        required = (
            *snapshot.occurrence_parts,
            *snapshot.locator_band_parts,
            *snapshot.lifecycle_parts,
            *snapshot.locator_feature_parts,
        )
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(f"feature snapshot is missing {path}")
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
                if table == _LOCATOR_KEYS_TABLE:
                    con.execute(
                        f"CREATE OR REPLACE TEMP TABLE {table} "
                        "(document_locator_key VARCHAR, request_ordinal BIGINT)"
                    )
                else:
                    con.execute(
                        f"CREATE OR REPLACE TEMP TABLE {table} "
                        "(document_locator_key VARCHAR)"
                    )
            con.execute(
                f"CREATE OR REPLACE TEMP TABLE {_ACCESSION_TABLE} (accession VARCHAR)"
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
        if values:
            con.execute(f"INSERT INTO {table} SELECT unnest(?)", [values])

    def _fill_locator_keys(self, values: Sequence[str]) -> None:
        con = self._require()
        con.execute(f"DELETE FROM {_LOCATOR_KEYS_TABLE}")
        if values:
            con.execute(
                f"""INSERT INTO {_LOCATOR_KEYS_TABLE}
                SELECT document_locator_key, request_ordinal
                FROM unnest(?) WITH ORDINALITY
                     AS requested(document_locator_key, request_ordinal)""",
                [values],
            )

    def _exclusion_predicate(self) -> str:
        return f"l.document_locator_key NOT IN (SELECT document_locator_key FROM {_SELECTED_TABLE})"

    def _locator_source(self) -> str:
        """The locator relation, projected so a date predicate sees one column; wrapping
        here keeps the outer alias `l` for every qualified reference in this module.
        """
        relation = self.locator_relation
        if self.filters.filters_dates():
            return f"{parsed_date_relation(relation, 'report_date')} l"
        return f"{relation} l"

    def _rows(
        self,
        query: str,
        params: Sequence[Any] = (),
        columns: Sequence[str] = POOL_COLUMNS,
    ) -> Iterator[dict[str, Any]]:
        result = self._require().execute(query, list(params))
        reader = result.to_arrow_reader(batch_size=resolve_read_batch_size())

        def iterate() -> Iterator[dict[str, Any]]:
            for batch in reader:
                for row_index in range(batch.num_rows):
                    yield {
                        name: batch.column(column_index)[row_index].as_py()
                        for column_index, name in enumerate(columns)
                    }

        return iterate()

    @staticmethod
    def _dimension(dimension: str) -> str:
        if dimension not in KNOWN_DIMENSIONS:
            raise ValueError(f"unknown selection dimension: {dimension!r}")
        return dimension

    # ------------------------------------------------------------ selection

    def register_selected(self, keys: Sequence[str]) -> None:
        self._fill(_SELECTED_TABLE, keys)

    def register_selected_relation(self, relation_sql: str) -> None:
        self._require().execute(
            f"INSERT INTO {_SELECTED_TABLE} "
            f"SELECT document_locator_key FROM ({relation_sql})"
        )

    def register_cik_iterable(self, ciks: Iterable[str]) -> None:
        con = self._require()
        con.execute(f"DELETE FROM {_CIK_TABLE}")
        values = iter(ciks)
        first = next(values, None)
        if first is None:
            return
        con.executemany(
            f"INSERT INTO {_CIK_TABLE} VALUES (?)",
            ((str(cik),) for cik in chain((first,), values)),
        )

    def register_cik_relation(self, relation_sql: str) -> None:
        con = self._require()
        con.execute(f"DELETE FROM {_CIK_TABLE}")
        con.execute(
            f"INSERT INTO {_CIK_TABLE} "
            f"SELECT DISTINCT CAST(cik AS VARCHAR) FROM ({relation_sql}) "
            "WHERE cik IS NOT NULL"
        )

    def add_selected(self, key: str) -> None:
        """Record one newly selected locator in the exclusion set."""
        self._require().execute(f"INSERT INTO {_SELECTED_TABLE} VALUES (?)", [key])

    # ---------------------------------------------------------------- pools

    def pool_for_value(
        self,
        dimension: str,
        value: str,
        limit: int = 60,
        *,
        exclude_accessions: Sequence[str] = (),
        exclude_selected_accessions: bool = False,
    ) -> Iterator[dict[str, Any]]:
        column = self._dimension(dimension)
        if dimension == "primary_exhibit_like":
            if exclude_selected_accessions:
                self._require().execute(f"DELETE FROM {_ACCESSION_TABLE}")
                accession_filter = (
                    f"l.representative_accession NOT IN ("
                    f"SELECT l2.representative_accession FROM {self.locator_relation} l2 "
                    f"JOIN {_SELECTED_TABLE} s USING (document_locator_key))"
                )
            else:
                self._fill(_ACCESSION_TABLE, exclude_accessions)
                accession_filter = (
                    "l.representative_accession NOT IN ("
                    f"SELECT accession FROM {_ACCESSION_TABLE})"
                )
            query = f"""
                WITH ranked AS (
                    SELECT {_POOL_SELECT},
                           ROW_NUMBER() OVER (
                               PARTITION BY l.representative_accession
                               ORDER BY {_ORDER_EXPR}
                           ) AS accession_rank
                    FROM {self._locator_source()}
                    WHERE {self._exclusion_predicate()}
                      AND {self.filters.predicate()}
                      AND l.{column} = ?
                      AND {accession_filter}
                )
                SELECT {_POOL_SELECT}
                FROM ranked
                WHERE accession_rank = 1
                ORDER BY {_RANKED_ORDER_EXPR}
                LIMIT {int(limit)}
            """
            return self._rows(query, [self.seed, value, self.seed])
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
    ) -> Iterator[dict[str, Any]]:
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

    def cell_availability(self) -> Iterator[tuple[str, str, int]]:
        """Every nonempty `(form, era)` cell with its eligible count, excluding the selected
        set: a cell with nothing left is not capacity.
        """
        result = self._require().execute(
            f"""
            SELECT l.form, l.era, COUNT(*) AS available
            FROM {self._locator_source()}
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
            GROUP BY l.form, l.era
            ORDER BY l.form, l.era
            """
        )
        reader = result.to_arrow_reader(batch_size=resolve_read_batch_size())

        def iterate() -> Iterator[tuple[str, str, int]]:
            for batch in reader:
                for row_index in range(batch.num_rows):
                    yield (
                        str(batch.column(0)[row_index].as_py()),
                        str(batch.column(1)[row_index].as_py()),
                        int(batch.column(2)[row_index].as_py()),
                    )

        return iterate()

    def populate_cell_availability(self, table: str) -> None:
        self._require().execute(
            f"""
            INSERT INTO {table} (form, era, available, selected, taken)
            SELECT l.form, l.era, COUNT(*), COALESCE(s.selected, 0), 0
            FROM {self._locator_source()}
            LEFT JOIN {table} s USING (form, era)
            WHERE {self._exclusion_predicate()} AND {self.filters.predicate()}
            GROUP BY l.form, l.era, s.selected
            ON CONFLICT (form, era) DO UPDATE SET available = excluded.available
            """
        )

    def pool_for_composite(
        self, filters: dict[str, Any], limit: int = 60
    ) -> Iterator[dict[str, Any]]:
        """Return candidates satisfying every filter of one composite stratum."""
        clauses = [self._exclusion_predicate(), self.filters.predicate()]
        clauses.extend(f"l.{self._dimension(dimension)} = ?" for dimension in filters)
        if "primary_exhibit_like" in filters:
            query = f"""
                WITH ranked AS (
                    SELECT {_POOL_SELECT},
                           ROW_NUMBER() OVER (
                               PARTITION BY l.representative_accession
                               ORDER BY {_ORDER_EXPR}
                           ) AS accession_rank
                    FROM {self._locator_source()}
                    WHERE {" AND ".join(clauses)}
                )
                SELECT {_POOL_SELECT}
                FROM ranked
                WHERE accession_rank = 1
                ORDER BY {_RANKED_ORDER_EXPR}
                LIMIT {int(limit)}
            """
            params = (
                [self.seed] + [str(value) for value in filters.values()] + [self.seed]
            )
            return self._rows(query, params)
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
    ) -> Iterator[dict[str, Any]]:
        """Up to `limit_per_cik` candidates per supplied CIK. The cap is per CIK, not
        global, or one mandatory seed registrant could consume the whole budget.
        """
        self.register_cik_iterable(ciks)
        return self.pool_for_registered_ciks(limit_per_cik=limit_per_cik)

    def pool_for_registered_ciks(
        self, limit_per_cik: int = 5, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        if (
            not self._require()
            .execute(f"SELECT 1 FROM {_CIK_TABLE} LIMIT 1")
            .fetchone()
        ):
            return iter(())
        limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
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
            {limit_clause}
        """
        return self._rows(query, [self.seed, self.seed])

    def candidate_page(self, page_index: int) -> Iterator[dict[str, Any]]:
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
    ) -> Iterator[dict[str, Any]]:
        """Feature rows of an existing selection, in the caller's order, so a parent
        selection's coverage accounting lines up with its keys.
        """
        if not locator_keys:
            return iter(())
        con = self._require()
        self._fill_locator_keys(locator_keys)
        missing_count, missing_keys = con.execute(
            f"""
            SELECT COUNT(*),
                   string_agg(document_locator_key, ', ' ORDER BY request_ordinal)
            FROM (
                SELECT r.document_locator_key, r.request_ordinal
                FROM {_LOCATOR_KEYS_TABLE} r
                WHERE NOT EXISTS (
                    SELECT 1 FROM {self.locator_relation} l
                    WHERE l.document_locator_key = r.document_locator_key
                )
                ORDER BY r.request_ordinal
                LIMIT 5
            )
            """
        ).fetchone()
        if missing_count:
            raise ValueError(
                "parent plan references locator keys absent from the selection "
                "snapshot: " + missing_keys
            )
        return self._rows(
            f"""
            SELECT {_QUALIFIED_POOL_SELECT}
            FROM {self.locator_relation} l
            JOIN {_LOCATOR_KEYS_TABLE} r
              ON l.document_locator_key = r.document_locator_key
            ORDER BY r.request_ordinal
            """,
            columns=POOL_COLUMNS,
        )

    def load_candidates_for_locator_relation(
        self, relation_sql: str
    ) -> Iterator[dict[str, Any]]:
        return self._rows(
            f"""
            SELECT {_QUALIFIED_POOL_SELECT}
            FROM {self.locator_relation} l
            JOIN ({relation_sql}) r
              ON l.document_locator_key = r.document_locator_key
            ORDER BY l.document_locator_key
            """,
            columns=POOL_COLUMNS,
        )

    def load_occurrences_for_locators(
        self, locator_keys: Sequence[str]
    ) -> Iterator[dict[str, Any]]:
        """Every occurrence belonging to the selected locators; a locator with two
        co-filers yields two rows, one per registrant's claim on one document.
        """
        if not locator_keys:
            return iter(())
        con = self._require()
        self._fill_locator_keys(locator_keys)
        result = con.execute(
            f"""
            SELECT {_QUALIFIED_OCCURRENCE_SELECT}
            FROM {self.occurrence_relation} o
            JOIN {_LOCATOR_KEYS_TABLE} r
              ON o.document_locator_key = r.document_locator_key
            ORDER BY o.document_locator_key, o.occurrence_id
            """,
            [],
        )
        reader = result.to_arrow_reader(batch_size=resolve_read_batch_size())

        def iterate() -> Iterator[dict[str, Any]]:
            for batch in reader:
                for row_index in range(batch.num_rows):
                    yield {
                        name: batch.column(column_index)[row_index].as_py()
                        for column_index, name in enumerate(OCCURRENCE_COLUMNS)
                    }

        return iterate()


__all__ = [
    "OCCURRENCE_COLUMNS",
    "POOL_COLUMNS",
    "CandidateFilters",
    "CandidateSource",
    "SelectionSessionError",
]
