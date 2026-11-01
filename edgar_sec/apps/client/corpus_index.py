"""Ingest-side writer for the corpus coordinate index.

Rows are projected from the facade's own display records — the
decomposition ingest already pays for — so the index carries the
tokenizer's output verbatim and cannot drift from live search.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.apps.client.batch import stream_filing_outcomes
from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.infra.storage.corpus_index import ConceptCoordinateRow, CorpusIndex


@dataclass(frozen=True, slots=True)
class IndexFailure:
    """One bundle's ingest failure, named so the batch can be audited."""

    bundle: str
    error: str


@dataclass(frozen=True, slots=True)
class IndexBatchResult:
    """A batch ingest's record: rows written and per-filing failures."""

    rows_written: int
    failures: tuple[IndexFailure, ...]


def rows_from_records(
    cik: str, accession: str, records: Mapping[str, DisplayRecord]
) -> tuple[ConceptCoordinateRow, ...]:
    """Project one filing's display records to index rows, qname-ordered."""
    rows = []
    for qname in sorted(records):
        record = records[qname]
        intent, total = record.residual_mass
        rows.append(
            ConceptCoordinateRow(
                cik=cik,
                accession=accession,
                concept_qname=qname,
                head=record.atom.head,
                modifiers=tuple(sorted(record.atom.modifiers)),
                residual_intent=intent,
                residual_total=total,
                item_type=record.item_type,
            )
        )
    return tuple(rows)


def index_facade(index: CorpusIndex, facade: Xbrl, *, cik: str) -> int:
    """Write one built facade's records to the index; return the row count."""
    rows = rows_from_records(cik, str(facade.accession), facade.facts.records)
    if not rows:
        return 0
    return index.replace_filing(rows)


def index_bundle(
    index: CorpusIndex, bundle_dir: Path, taxonomy: DomainTaxonomy, *, cik: str
) -> int:
    """Build one bundle's facade and write its records; return the row count."""
    return index_facade(index, Xbrl.from_bundle(bundle_dir, taxonomy), cik=cik)


_WORKER_TAXONOMY: DomainTaxonomy | None = None


def _worker_taxonomy() -> DomainTaxonomy:
    """This process's domain taxonomy, loaded lazily on first use."""
    global _WORKER_TAXONOMY
    if _WORKER_TAXONOMY is None:
        _WORKER_TAXONOMY = load_domain_taxonomy()
    return _WORKER_TAXONOMY


def _bundle_rows(task: tuple[str, str]) -> tuple[ConceptCoordinateRow, ...]:
    """One bundle's index rows, computed in a pool worker."""
    bundle_dir, cik = task
    facade = Xbrl.from_bundle(Path(bundle_dir), _worker_taxonomy())
    return rows_from_records(cik, str(facade.accession), facade.facts.records)


def index_bundles(
    index: CorpusIndex,
    bundles: Sequence[tuple[Path, str]],
    *,
    workers: int | None = None,
) -> IndexBatchResult:
    """Index many bundles under the batch streaming contract.

    Rows stream from each filing as it resolves and are written on
    arrival; a malformed bundle fails only its own filing.
    """
    tasks = tuple((str(bundle_dir), cik) for bundle_dir, cik in bundles)
    written = 0
    failures = []
    for outcome in stream_filing_outcomes(tasks, _bundle_rows, workers=workers):
        if outcome.ok:
            if outcome.value:
                written += index.replace_filing(outcome.value)
        else:
            bundle_dir, _cik = outcome.unit
            failures.append(
                IndexFailure(
                    bundle=Path(bundle_dir).name,
                    error=outcome.error if outcome.error is not None else "",
                )
            )
    return IndexBatchResult(rows_written=written, failures=tuple(failures))


__all__ = [
    "IndexBatchResult",
    "IndexFailure",
    "index_bundle",
    "index_bundles",
    "index_facade",
    "rows_from_records",
]
