"""Ingest-side writer for the corpus coordinate index.

Rows are projected from the facade's own display records — the
decomposition ingest already pays for — so the index carries the
tokenizer's output verbatim and cannot drift from live search.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import (
    calculation_arcs_from_arrow_table,
    facts_from_arrow_table,
    presentation_arcs_from_arrow_table,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.corpus_index import ConceptCoordinateRow, CorpusIndex


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


def _facade_from_bundle(bundle_dir: Path, taxonomy: DomainTaxonomy) -> Xbrl:
    """Build the full-fidelity facade over one bundle folder."""
    facts = facts_from_arrow_table(pq.read_table(bundle_dir / "facts.parquet"))
    accessions = {str(fact.accession) for fact in facts}
    if len(accessions) != 1:
        raise ValueError(f"bundle {bundle_dir.name} accessions: {sorted(accessions)}")
    calc = calculation_arcs_from_arrow_table(
        pq.read_table(bundle_dir / "calculation_arcs.parquet")
    )
    pres = presentation_arcs_from_arrow_table(
        pq.read_table(bundle_dir / "presentation_arcs.parquet")
    )
    filing = FilingXbrl(
        accession=AccessionNumber.from_any(accessions.pop()),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=calc, presentation_arcs=pres),
    )
    return Xbrl(filing, taxonomy)


def index_bundle(
    index: CorpusIndex, bundle_dir: Path, taxonomy: DomainTaxonomy, *, cik: str
) -> int:
    """Build one bundle's facade and write its records; return the row count."""
    return index_facade(index, _facade_from_bundle(bundle_dir, taxonomy), cik=cik)


def _bundle_rows(task: tuple[str, str]) -> tuple[ConceptCoordinateRow, ...]:
    """One bundle's index rows, computed in a pool worker."""
    bundle_dir, cik = task
    facade = _facade_from_bundle(Path(bundle_dir), load_domain_taxonomy())
    return rows_from_records(cik, str(facade.accession), facade.facts.records)


def index_bundles(
    index: CorpusIndex,
    bundles: Sequence[tuple[Path, str]],
    *,
    workers: int | None = None,
) -> int:
    """Index many bundles, computing rows per filing in a worker pool.

    The pool width comes from derive_resources() unless overridden;
    writes stay in this process because the index has one writer.
    """
    tasks = tuple((str(bundle_dir), cik) for bundle_dir, cik in bundles)
    if not tasks:
        return 0
    width = workers if workers is not None else derive_resources().workers
    if width <= 1 or len(tasks) == 1:
        taxonomy = load_domain_taxonomy()
        computed = []
        for bundle_dir, cik in tasks:
            facade = _facade_from_bundle(Path(bundle_dir), taxonomy)
            computed.append(
                rows_from_records(cik, str(facade.accession), facade.facts.records)
            )
    else:
        with ProcessPoolExecutor(max_workers=width) as pool:
            computed = list(pool.map(_bundle_rows, tasks))
    written = 0
    for rows in computed:
        if rows:
            written += index.replace_filing(rows)
    return written


__all__ = [
    "index_bundle",
    "index_bundles",
    "index_facade",
    "rows_from_records",
]
