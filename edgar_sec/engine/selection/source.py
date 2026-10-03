"""Bounded, storage-backed candidate access for stratified selection.

The selector never holds the candidate pool in memory. It asks this module for
a pool satisfying a dimension value, a composite filter set, a CIK set, or one
deterministic page, and gets back at most ``limit`` rows. That bound is the
point: a corpus of millions of locators has to be selectable on a machine whose
memory budget is derived from cgroup limits, not from the corpus.

Four corrections against v1:

* **The tie-break seed is bound, not interpolated.** v1 wrote
  ``ORDER BY md5('{seed}' || key)`` with ``seed`` read from a policy document,
  so a policy file was a SQL injection surface. Every value reaching SQL is now
  a bound parameter, and the digest is SHA-256 rather than MD5 to match M6.
* **Selected keys are joined through temp tables, not ``IN`` lists.** v1 chunked
  a 5,000-element ``IN`` list and re-parsed it per chunk, so loading the parent
  selection for a 100k-locator plan built twenty multi-megabyte statements. One
  temp table plus a join is a single pass.
* **Every column name is validated** against ``KNOWN_DIMENSIONS``. v1
  interpolated the dimension name straight into the predicate, so a policy could
  query any column the snapshot happened to carry.
* **Row-to-dict mapping is strict.** A projection that drifts from the column
  tuple used to build it would silently truncate every row rather than raise.
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
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import (
    date_selection_sql,
    parsed_date_relation,
    sql_literal,
    suffix_sql,
)

# The locator columns the selector reasons over. A tuple rather than a
# comma-joined string so the SELECT list and the row-to-dict zip are generated
# from one source.
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

# Occurrence columns returned for the active selection, so a consumer can write
# a work order without re-reading the snapshot.
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

# One definition of the tie-break order, referenced by every pool query.
#
# The seed must sit *inside* the concatenation, not beside it. DuckDB
# constant-folds `constant || column` to a constant, so `sha256(?) || key`
# silently sorts every row equal and the pool comes back in file order --
# which looks deterministic and is, but is not seed-dependent at all.
_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || l.document_locator_key)"
_RANKED_ORDER_EXPR = "sha256(CAST(? AS VARCHAR) || ranked.document_locator_key)"

_SELECTED_TABLE = "selected_keys"
_LOCATOR_KEYS_TABLE = "requested_locator_keys"
_CIK_TABLE = "requested_ciks"


class SelectionSessionError(RuntimeError):
    """A candidate query was attempted outside an open session."""


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    """The policy-level filters applied to every pool query.

    Built once per source so the predicate is constructed once rather than per
    call, and so the same filter set cannot drift between pool kinds.
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
            # Suffixes apply to the effective document path, which is the
            # primary document for an observed row and the synthetic
            # submission-bundle path for a fallback locator.
            clauses.append(suffix_sql("l.document_path", self.document_suffixes))
        if self.date_selection:
            # Applied here rather than after selection, so a locator outside the
            # declared dates cannot be drawn by any phase: not by a floor, not by
            # the weighted fill, not by the reserve. A date selection that only
            # filtered the final list would still let out-of-range candidates
            # consume quota on the way there.
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
        """Open the candidate session, creating the working tables.

        The connection is in-memory: v1 opened a ``selection_session.duckdb``
        inside the snapshot directory and deleted it afterwards, which left a
        partially written database behind whenever the process died mid-run.
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
        """The locator relation, projected so a date predicate sees one column.

        Only the pool queries need this: they are the ones carrying the filter
        set. Wrapping here rather than per query is what keeps the parse to one
        occurrence per row instead of one per predicate reference, and the outer
        alias stays ``l`` so every qualified reference in this module is
        unaffected.
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
        """Replace the exclusion set with exactly ``keys``."""
        self._fill(_SELECTED_TABLE, keys)

    def add_selected(self, key: str) -> None:
        """Record one newly selected locator in the exclusion set."""
        self._require().execute(f"INSERT INTO {_SELECTED_TABLE} VALUES (?)", [key])

    # ---------------------------------------------------------------- pools

    def pool_for_value(
        self, dimension: str, value: str, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` candidates whose ``dimension`` equals ``value``."""
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
        """Return candidates in one form-by-era cell, in the shared tie-break order.

        The conjunction is over two columns of the same locator row, so it reads
        as one stratum rather than a floor on each dimension separately: a floor
        on ``form`` cannot tell a cell from any other row of that form.
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
        """Return every nonempty ``(form, era)`` cell with its eligible count.

        One grouped pass, so the allocator can tell a cell that is small from a
        cell that is empty without asking per cell. Excludes the already-selected
        set, matching what the pool query would draw from: a cell whose remaining
        candidates are gone must not be counted as capacity.
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
        """Return up to ``limit_per_cik`` candidates for each supplied CIK.

        The cap is per CIK rather than global: seed filers are mandatory, so
        without a per-CIK bound one seed registrant could consume the entire
        selection budget.
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
        """Return one deterministic page of unselected candidates.

        Paging is ``OFFSET`` over a seed-derived total order, so a given page
        index yields the same rows for the same seed and snapshot.
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
        """Load the feature rows of an existing selection, in the given order.

        Order is the caller's, not the store's: a parent selection's rows must
        land in the order of its keys so coverage accounting lines up.
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
        """Return every occurrence belonging to the selected locators.

        A locator with two co-filer occurrences yields two rows: the document is
        one, but each registrant's claim on it is a separate work item.
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
