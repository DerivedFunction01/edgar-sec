"""DuckDB corpus index of per-concept atom coordinates.

Rows are caller-derived data — one per (cik, accession, concept) —
persisted for screening; this package stores and filters them and
attaches no equivalence semantics to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import TYPE_CHECKING

from edgar_sec.infra.storage.duckdb import connect

if TYPE_CHECKING:
    from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS concept_coordinates (
    cik VARCHAR NOT NULL,
    accession VARCHAR NOT NULL,
    concept_qname VARCHAR NOT NULL,
    head VARCHAR NOT NULL,
    modifiers VARCHAR[] NOT NULL,
    residual_intent INTEGER NOT NULL,
    residual_total INTEGER NOT NULL,
    item_type VARCHAR,
    PRIMARY KEY (cik, accession, concept_qname)
)
"""

_HEAD_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_concept_coordinates_head
ON concept_coordinates (head)
"""

_INSERT_SQL = """
INSERT INTO concept_coordinates (
    cik, accession, concept_qname, head, modifiers,
    residual_intent, residual_total, item_type
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_DELETE_FILING_SQL = """
DELETE FROM concept_coordinates WHERE cik = ? AND accession = ?
"""

_SELECT_COLUMNS = (
    "cik, accession, concept_qname, head, modifiers,"
    " residual_intent, residual_total, item_type"
)

_ROWS_FOR_HEADS_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM concept_coordinates
WHERE head IN (SELECT * FROM unnest(?))
ORDER BY cik, accession, concept_qname
"""

_ROWS_FOR_FILING_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM concept_coordinates
WHERE cik = ? AND accession = ?
ORDER BY concept_qname
"""

_ROWS_AT_COORDINATE_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM concept_coordinates
WHERE head = ? AND len(list_intersect(modifiers, ?)) = ?
ORDER BY cik, accession, concept_qname
"""

_PEER_FILINGS_SQL = """
SELECT DISTINCT peer.cik, peer.accession
FROM concept_coordinates AS own
JOIN concept_coordinates AS peer
    ON peer.head = own.head AND peer.modifiers = own.modifiers
WHERE own.cik = ? AND own.accession = ?
    AND NOT (peer.cik = ? AND peer.accession = ?)
ORDER BY peer.cik, peer.accession
"""

_ROW_COUNT_SQL = "SELECT count(*) FROM concept_coordinates"

_FILING_COUNT_SQL = """
SELECT count(*) FROM (
    SELECT DISTINCT cik, accession FROM concept_coordinates
)
"""


@dataclass(frozen=True, slots=True)
class ConceptCoordinateRow:
    """One concept's persisted atom coordinate within one filing."""

    cik: str
    accession: str
    concept_qname: str
    head: str
    modifiers: tuple[str, ...]
    residual_intent: int
    residual_total: int
    item_type: str | None


def _to_row(record: tuple) -> ConceptCoordinateRow:
    """Assemble one stored record as a coordinate row."""
    return ConceptCoordinateRow(
        cik=record[0],
        accession=record[1],
        concept_qname=record[2],
        head=record[3],
        modifiers=tuple(record[4]),
        residual_intent=int(record[5]),
        residual_total=int(record[6]),
        item_type=record[7],
    )


class CorpusIndex:
    """A DuckDB file of concept coordinates, replaced per filing on re-ingest."""

    def __init__(
        self,
        database: str | PathLike[str] = ":memory:",
        profile: RuntimeResourceProfile | None = None,
    ) -> None:
        self._con = connect(profile, database=database)
        self._con.execute(_SCHEMA_SQL)
        self._con.execute(_HEAD_INDEX_SQL)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._con.close()

    def __enter__(self) -> CorpusIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def replace_filing(self, rows: tuple[ConceptCoordinateRow, ...]) -> int:
        """Replace one filing's rows atomically; return the row count.

        All rows must name the same (cik, accession): a filing is the
        unit of replacement, so a mixed batch is refused.
        """
        if not rows:
            raise ValueError("replace_filing requires at least one row")
        keys = {(row.cik, row.accession) for row in rows}
        if len(keys) != 1:
            raise ValueError(f"rows span multiple filings: {sorted(keys)}")
        ((cik, accession),) = keys
        params = [
            (
                row.cik,
                row.accession,
                row.concept_qname,
                row.head,
                list(row.modifiers),
                row.residual_intent,
                row.residual_total,
                row.item_type,
            )
            for row in rows
        ]
        self._con.execute("BEGIN TRANSACTION")
        try:
            self._con.execute(_DELETE_FILING_SQL, [cik, accession])
            self._con.executemany(_INSERT_SQL, params)
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise
        return len(rows)

    def rows_for_heads(
        self, heads: tuple[str, ...]
    ) -> tuple[ConceptCoordinateRow, ...]:
        """Every row whose head is one of ``heads``, in filing order."""
        if not heads:
            return ()
        records = self._con.execute(_ROWS_FOR_HEADS_SQL, [list(heads)]).fetchall()
        return tuple(_to_row(record) for record in records)

    def rows_for_filing(
        self, cik: str, accession: str
    ) -> tuple[ConceptCoordinateRow, ...]:
        """Every row of one filing, ordered by concept qname."""
        records = self._con.execute(_ROWS_FOR_FILING_SQL, [cik, accession]).fetchall()
        return tuple(_to_row(record) for record in records)

    def rows_at_coordinate(
        self, head: str, modifiers: tuple[str, ...]
    ) -> tuple[ConceptCoordinateRow, ...]:
        """Rows at a head whose modifiers cover ``modifiers`` (the scalar rule)."""
        records = self._con.execute(
            _ROWS_AT_COORDINATE_SQL, [head, list(modifiers), len(modifiers)]
        ).fetchall()
        return tuple(_to_row(record) for record in records)

    def peer_filings(self, cik: str, accession: str) -> tuple[tuple[str, str], ...]:
        """Other filings sharing at least one exact coordinate with a filing."""
        records = self._con.execute(
            _PEER_FILINGS_SQL, [cik, accession, cik, accession]
        ).fetchall()
        return tuple((record[0], record[1]) for record in records)

    def row_count(self) -> int:
        """Total coordinate rows in the index."""
        return int(self._con.execute(_ROW_COUNT_SQL).fetchone()[0])

    def filing_count(self) -> int:
        """Distinct filings in the index."""
        return int(self._con.execute(_FILING_COUNT_SQL).fetchone()[0])


__all__ = [
    "ConceptCoordinateRow",
    "CorpusIndex",
]
