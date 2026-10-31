"""Per-process concept-to-atom table, tokenized once from the loaded taxonomy.

The table is the cache: it is built from the taxonomy bytes the process
itself loaded and lives for the process lifetime, so no freshness
contract or persisted artefact exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re

from edgar_sec.engine.xbrl.normalize.decomposer import residual_counts
from edgar_sec.engine.xbrl.normalize.lexicon import EvidenceContext
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer, TokenizedFact
from edgar_sec.engine.xbrl.taxonomy.archive import (
    bundle_namespaces,
    current_table,
    namespace_key,
    slice_table,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.duckdb import connect, sql_path_list


@dataclass(frozen=True, slots=True)
class CohortEntry:
    """One cohort filing: its accession, bundle facts path, and firm label."""

    accession: str
    facts_path: Path
    firm: str = ""


@dataclass(frozen=True, slots=True)
class ConceptRecord:
    """One concept's full tokenized record as carried by the table."""

    qname: str
    atom: Atom
    presumed_atom: Atom
    presumed_signature: str
    residuals: tuple[str, ...] = ()
    residual_intent: int = 0
    residual_total: int = 0
    derived_horizon: str | None = None
    presumed_modifier: str | None = None
    item_type: str | None = None


class ConceptTable:
    """Concept records over one taxonomy, each qname tokenized exactly once."""

    def __init__(
        self,
        taxonomy: DomainTaxonomy,
        tokenizer: ConceptTokenizer,
        records: Mapping[str, ConceptRecord],
        declarations: Mapping[str, ConceptDeclaration],
        item_types: Mapping[str, str],
    ) -> None:
        """Bind the taxonomy, its tokenizer, and the built records."""
        self._taxonomy = taxonomy
        self._tokenizer = tokenizer
        self._records = dict(records)
        self._declarations = dict(declarations)
        self._item_types = dict(item_types)
        grouped: dict[Atom, list[str]] = {}
        for qname, record in self._records.items():
            grouped.setdefault(record.atom, []).append(qname)
        self._qnames_by_atom = {
            atom: tuple(sorted(qnames)) for atom, qnames in grouped.items()
        }
        self._residual_counts = {
            qname: (record.residual_intent, record.residual_total)
            for qname, record in self._records.items()
        }

    @property
    def taxonomy(self) -> DomainTaxonomy:
        """The taxonomy the table was tokenized from."""
        return self._taxonomy

    @property
    def records(self) -> Mapping[str, ConceptRecord]:
        """All concept records, keyed by qname."""
        return self._records

    @property
    def distinct_atoms(self) -> tuple[Atom, ...]:
        """The distinct stated atoms across all records, signature-ordered."""
        atoms = {record.atom for record in self._records.values()}
        return tuple(sorted(atoms, key=lambda atom: canonical_json(atom.to_dict())))

    @property
    def qnames_by_atom(self) -> Mapping[Atom, tuple[str, ...]]:
        """Stated atom to the sorted qnames carrying it."""
        return self._qnames_by_atom

    @property
    def residual_counts(self) -> dict[str, tuple[int, int]]:
        """Per-qname (intent, total) residual mass, for ranking consumers."""
        return self._residual_counts

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, qname: str) -> bool:
        return qname in self._records

    def record(self, qname: str) -> ConceptRecord:
        """Return one concept's record; KeyError when not in the table."""
        return self._records[qname]

    def declaration(self, qname: str) -> ConceptDeclaration | None:
        """Effective declaration for a qname: extension first, table underneath."""
        return declaration_for(qname, self._item_types, self._declarations)

    def tokenize(
        self, qname: str, evidence: EvidenceContext | None = None
    ) -> TokenizedFact:
        """Tokenize a qname with the table's effective declaration for it."""
        return self._tokenizer.tokenize(qname, self.declaration(qname), evidence)


def build_concept_table(
    taxonomy: DomainTaxonomy,
    qnames: Iterable[str],
    *,
    declarations: Iterable[ConceptDeclaration] = (),
    item_types: Mapping[str, str] | None = None,
) -> ConceptTable:
    """Tokenize each distinct qname once and return the table.

    Declarations merge the standard item-type table under any extension
    declarations supplied, matching the facade's merged view.
    """
    if item_types is None:
        item_types = current_table()
    tokenizer = ConceptTokenizer(taxonomy)
    extension = {item.concept_qname: item for item in declarations}
    records: dict[str, ConceptRecord] = {}
    merged: dict[str, ConceptDeclaration] = {}
    for qname in sorted(set(qnames)):
        declaration = declaration_for(qname, item_types, extension)
        if declaration is not None:
            merged[qname] = declaration
        record = tokenizer.tokenize(qname, declaration)
        intent, total = residual_counts(record.residuals)
        added = record.presumed_atom.modifiers - record.atom.modifiers
        records[qname] = ConceptRecord(
            qname=qname,
            atom=record.atom,
            presumed_atom=record.presumed_atom,
            presumed_signature=canonical_json(record.presumed_atom.to_dict()),
            residuals=record.residuals,
            residual_intent=intent,
            residual_total=total,
            derived_horizon=record.derived_horizon,
            presumed_modifier=next(iter(added)) if len(added) == 1 else None,
            item_type=declaration.item_type if declaration is not None else None,
        )
    return ConceptTable(taxonomy, tokenizer, records, merged, item_types)


def cohort_qnames(entries: Sequence[CohortEntry]) -> tuple[str, ...]:
    """The distinct concept qnames reported across a cohort's bundles."""
    if not entries:
        return ()
    paths = [str(entry.facts_path) for entry in entries]
    query = f"SELECT DISTINCT concept_qname FROM read_parquet({sql_path_list(paths)})"
    con = connect()
    try:
        rows = con.execute(query).fetchall()
    finally:
        con.close()
    return tuple(sorted(row[0] for row in rows))


_DIGITS = re.compile(r"\d+")


def _version_order(version: str) -> tuple[int, ...]:
    """Sortable key for an archive version token (year, then quarter/date)."""
    parts = tuple(int(part) for part in _DIGITS.findall(version))
    return parts + (0,) * (3 - len(parts))


def _cohort_item_types(entries: Sequence[CohortEntry]) -> dict[str, str]:
    """Vintage-resolved item-type table for a cohort's reported qnames.

    Each qname takes its type from the newest reporter's slice carrying it.
    """
    if not entries:
        return {}
    namespaces_by_accession = {
        entry.accession: bundle_namespaces(entry.facts_path.parent) for entry in entries
    }
    paths = [str(entry.facts_path) for entry in entries]
    query = (
        "SELECT DISTINCT concept_qname, accession FROM read_parquet"
        f"({sql_path_list(paths)})"
    )
    con = connect()
    try:
        pairs = con.execute(query).fetchall()
    finally:
        con.close()
    reporters: dict[str, list[tuple[tuple[int, ...], str, str]]] = {}
    for qname, accession in pairs:
        prefix = qname.partition(":")[0]
        uri = namespaces_by_accession.get(accession, {}).get(prefix)
        if uri is None:
            continue
        key = namespace_key(uri)
        if key is None:
            continue
        reporters.setdefault(qname, []).append((_version_order(key[1]), key[0], key[1]))
    tables: dict[tuple[str, str, str], dict[str, str]] = {}

    def _slice(taxonomy: str, version: str, prefix: str) -> dict[str, str]:
        key = (taxonomy, version, prefix)
        if key not in tables:
            tables[key] = slice_table(taxonomy, version, prefix)
        return tables[key]

    table: dict[str, str] = {}
    for qname, candidates in reporters.items():
        prefix = qname.partition(":")[0]
        for _, taxonomy, version in sorted(candidates, reverse=True):
            item_type = _slice(taxonomy, version, prefix).get(qname)
            if item_type is not None:
                table[qname] = item_type
                break
    return table


def build_cohort_table(
    taxonomy: DomainTaxonomy,
    entries: Sequence[CohortEntry],
    *,
    declarations: Iterable[ConceptDeclaration] = (),
    item_types: Mapping[str, str] | None = None,
) -> ConceptTable:
    """Build the concept table over a cohort's distinct reported qnames."""
    if item_types is None:
        item_types = _cohort_item_types(entries)
    return build_concept_table(
        taxonomy,
        cohort_qnames(entries),
        declarations=declarations,
        item_types=item_types,
    )


__all__ = [
    "CohortEntry",
    "ConceptRecord",
    "ConceptTable",
    "build_cohort_table",
    "build_concept_table",
    "cohort_qnames",
]
