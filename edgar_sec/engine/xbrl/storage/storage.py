"""Parquet serialization and deserialization for linkbases, arcs, and facts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.discovery.discovery import DiscoveredLinkbase
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    DefinitionArc,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.parquet import write_parquet_table

LINKBASE_INVENTORY_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("cik", pa.int64(), nullable=False),
        pa.field("linkbase_type", pa.string(), nullable=False),
        pa.field("document_type", pa.string(), nullable=False),
        pa.field("filename", pa.string(), nullable=False),
        pa.field("archive_url", pa.string(), nullable=False),
        pa.field("byte_size", pa.int64(), nullable=True),
        pa.field("sequence", pa.int32(), nullable=True),
        pa.field("description", pa.string(), nullable=True),
    ]
)

CALCULATION_ARC_SCHEMA = pa.schema(
    [
        pa.field("parent_qname", pa.string(), nullable=False),
        pa.field("child_qname", pa.string(), nullable=False),
        pa.field("weight", pa.float64(), nullable=False),
        pa.field("order", pa.float64(), nullable=True),
        pa.field("role_uri", pa.string(), nullable=True),
    ]
)

PRESENTATION_ARC_SCHEMA = pa.schema(
    [
        pa.field("parent_qname", pa.string(), nullable=False),
        pa.field("child_qname", pa.string(), nullable=False),
        pa.field("order", pa.float64(), nullable=True),
        pa.field("role_uri", pa.string(), nullable=True),
    ]
)

DEFINITION_ARC_SCHEMA = pa.schema(
    [
        pa.field("parent_qname", pa.string(), nullable=False),
        pa.field("child_qname", pa.string(), nullable=False),
        pa.field("arcrole", pa.string(), nullable=False),
        pa.field("order", pa.float64(), nullable=True),
        pa.field("role_uri", pa.string(), nullable=True),
        pa.field("usable", pa.bool_(), nullable=True),
        pa.field("closed", pa.bool_(), nullable=True),
        pa.field("context_element", pa.string(), nullable=True),
        pa.field("target_role", pa.string(), nullable=True),
    ]
)

DECLARATION_SCHEMA = pa.schema(
    [
        pa.field("concept_qname", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("period_type", pa.string(), nullable=True),
        pa.field("balance", pa.string(), nullable=True),
        pa.field("substitution_group", pa.string(), nullable=True),
        pa.field("item_type", pa.string(), nullable=True),
        pa.field("abstract", pa.bool_(), nullable=False),
    ]
)

XBRL_FACT_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("concept_qname", pa.string(), nullable=False),
        pa.field("numeric_value", pa.float64(), nullable=True),
        pa.field("text_value", pa.string(), nullable=True),
        pa.field("unit", pa.string(), nullable=True),
        pa.field("decimals", pa.int32(), nullable=True),
        pa.field("period_type", pa.string(), nullable=False),
        pa.field("start_date", pa.string(), nullable=True),
        pa.field("end_date", pa.string(), nullable=True),
        pa.field("instant_date", pa.string(), nullable=True),
        pa.field("dimensions_json", pa.string(), nullable=False),
        pa.field("context_id", pa.string(), nullable=True),
    ]
)


def linkbases_to_arrow_table(
    linkbases: Sequence[DiscoveredLinkbase],
) -> pa.Table:
    """Convert discovered linkbase records to a typed PyArrow table."""
    arrays = [
        pa.array([str(lb.accession) for lb in linkbases], type=pa.string()),
        pa.array([int(lb.cik) for lb in linkbases], type=pa.int64()),
        pa.array([lb.linkbase_type.value for lb in linkbases], type=pa.string()),
        pa.array([lb.document_type for lb in linkbases], type=pa.string()),
        pa.array([lb.filename for lb in linkbases], type=pa.string()),
        pa.array([lb.archive_url for lb in linkbases], type=pa.string()),
        pa.array([lb.byte_size for lb in linkbases], type=pa.int64()),
        pa.array([lb.sequence for lb in linkbases], type=pa.int32()),
        pa.array([lb.description for lb in linkbases], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=LINKBASE_INVENTORY_SCHEMA)


def write_linkbase_parquet(
    linkbases: Sequence[DiscoveredLinkbase],
    destination: Path | str,
) -> int:
    """Write discovered linkbases into an atomic, compressed Parquet file."""
    table = linkbases_to_arrow_table(linkbases)
    return write_parquet_table(table, destination)


def read_linkbase_parquet(source: Path | str) -> pa.Table:
    """Read linkbase inventory Parquet file into an Arrow Table."""
    return pq.read_table(os.fspath(source))


def calculation_arcs_to_arrow_table(
    arcs: Sequence[CalculationArc],
) -> pa.Table:
    """Convert calculation arcs into a typed PyArrow table."""
    arrays = [
        pa.array([a.parent_qname for a in arcs], type=pa.string()),
        pa.array([a.child_qname for a in arcs], type=pa.string()),
        pa.array([float(a.weight) for a in arcs], type=pa.float64()),
        pa.array([a.order for a in arcs], type=pa.float64()),
        pa.array([a.role_uri or "" for a in arcs], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=CALCULATION_ARC_SCHEMA)


def calculation_arcs_from_arrow_table(
    table: pa.Table,
) -> tuple[CalculationArc, ...]:
    """Rebuild calculation arcs from a calculation-arcs Arrow table."""
    return tuple(
        CalculationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            weight=row["weight"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in table.to_pylist()
    )


def write_calculation_arcs_parquet(
    arcs: Sequence[CalculationArc],
    destination: Path | str,
) -> int:
    """Write calculation arcs into an atomic Parquet file."""
    table = calculation_arcs_to_arrow_table(arcs)
    return write_parquet_table(table, destination)


def presentation_arcs_to_arrow_table(
    arcs: Sequence[PresentationArc],
) -> pa.Table:
    """Convert presentation arcs into a typed PyArrow table."""
    arrays = [
        pa.array([a.parent_qname for a in arcs], type=pa.string()),
        pa.array([a.child_qname for a in arcs], type=pa.string()),
        pa.array([a.order for a in arcs], type=pa.float64()),
        pa.array([a.role_uri or "" for a in arcs], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=PRESENTATION_ARC_SCHEMA)


def presentation_arcs_from_arrow_table(
    table: pa.Table,
) -> tuple[PresentationArc, ...]:
    """Rebuild presentation arcs from a presentation-arcs Arrow table."""
    return tuple(
        PresentationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in table.to_pylist()
    )


def write_presentation_arcs_parquet(
    arcs: Sequence[PresentationArc],
    destination: Path | str,
) -> int:
    """Write presentation arcs into an atomic Parquet file."""
    table = presentation_arcs_to_arrow_table(arcs)
    return write_parquet_table(table, destination)


def definition_arcs_to_arrow_table(
    arcs: Sequence[DefinitionArc],
) -> pa.Table:
    """Convert definition arcs into a typed PyArrow table."""
    arrays = [
        pa.array([a.parent_qname for a in arcs], type=pa.string()),
        pa.array([a.child_qname for a in arcs], type=pa.string()),
        pa.array([a.arcrole for a in arcs], type=pa.string()),
        pa.array([a.order for a in arcs], type=pa.float64()),
        pa.array([a.role_uri for a in arcs], type=pa.string()),
        pa.array([a.usable for a in arcs], type=pa.bool_()),
        pa.array([a.closed for a in arcs], type=pa.bool_()),
        pa.array([a.context_element for a in arcs], type=pa.string()),
        pa.array([a.target_role for a in arcs], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=DEFINITION_ARC_SCHEMA)


def definition_arcs_from_arrow_table(
    table: pa.Table,
) -> tuple[DefinitionArc, ...]:
    """Rebuild definition arcs from a definition-arcs Arrow table."""
    return tuple(
        DefinitionArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            arcrole=row["arcrole"],
            order=row["order"],
            role_uri=row["role_uri"],
            usable=row["usable"],
            closed=row["closed"],
            context_element=row["context_element"],
            target_role=row["target_role"],
        )
        for row in table.to_pylist()
    )


def write_definition_arcs_parquet(
    arcs: Sequence[DefinitionArc],
    destination: Path | str,
) -> int:
    """Write definition arcs into an atomic Parquet file."""
    table = definition_arcs_to_arrow_table(arcs)
    return write_parquet_table(table, destination)


def facts_to_arrow_table(facts: Sequence[XbrlFact]) -> pa.Table:
    """Convert XBRL facts into a typed PyArrow table."""
    num_vals: list[float | None] = []
    text_vals: list[str | None] = []
    for f in facts:
        if isinstance(f.value, (int, float)):
            num_vals.append(float(f.value))
            text_vals.append(None)
        else:
            num_vals.append(None)
            text_vals.append(str(f.value) if f.value is not None else None)

    arrays = [
        pa.array([str(f.accession) for f in facts], type=pa.string()),
        pa.array([f.concept_qname for f in facts], type=pa.string()),
        pa.array(num_vals, type=pa.float64()),
        pa.array(text_vals, type=pa.string()),
        pa.array([f.unit for f in facts], type=pa.string()),
        pa.array([f.decimals for f in facts], type=pa.int32()),
        pa.array([f.period_type for f in facts], type=pa.string()),
        pa.array([f.start_date for f in facts], type=pa.string()),
        pa.array([f.end_date for f in facts], type=pa.string()),
        pa.array([f.instant_date for f in facts], type=pa.string()),
        pa.array(
            [canonical_json(dict(f.dimensions)) for f in facts],
            type=pa.string(),
        ),
        pa.array([f.context_id for f in facts], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=XBRL_FACT_SCHEMA)


def write_facts_parquet(
    facts: Sequence[XbrlFact],
    destination: Path | str,
) -> int:
    """Write XBRL facts into an atomic Parquet file."""
    table = facts_to_arrow_table(facts)
    return write_parquet_table(table, destination)


def declarations_to_arrow_table(
    declarations: Sequence[ConceptDeclaration],
) -> pa.Table:
    """Convert concept declarations into a typed PyArrow table."""
    arrays = [
        pa.array([d.concept_qname for d in declarations], type=pa.string()),
        pa.array([d.name for d in declarations], type=pa.string()),
        pa.array([d.period_type for d in declarations], type=pa.string()),
        pa.array([d.balance for d in declarations], type=pa.string()),
        pa.array([d.substitution_group for d in declarations], type=pa.string()),
        pa.array([d.item_type for d in declarations], type=pa.string()),
        pa.array([d.abstract for d in declarations], type=pa.bool_()),
    ]
    return pa.Table.from_arrays(arrays, schema=DECLARATION_SCHEMA)


def write_declarations_parquet(
    declarations: Sequence[ConceptDeclaration],
    destination: Path | str,
) -> int:
    """Write concept declarations into an atomic Parquet file."""
    table = declarations_to_arrow_table(declarations)
    return write_parquet_table(table, destination)


def read_declarations_parquet(source: Path | str) -> pa.Table:
    """Read declarations; beside a namespaces.json, merge archive rows beneath.

    Archive declarations for the bundle's referenced qnames sit under the
    file's own rows, which win per qname; other paths read as stored.
    """
    path = Path(source)
    table = pq.read_table(path)
    if not (path.parent / "namespaces.json").is_file():
        return table
    own = declarations_from_arrow_table(table)
    supplied = _archive_declarations(path.parent, own)
    if not supplied:
        return table
    return declarations_to_arrow_table(own + supplied)


def _archive_declarations(
    bundle_dir: Path, own: tuple[ConceptDeclaration, ...]
) -> tuple[ConceptDeclaration, ...]:
    """Archive declarations for a bundle's referenced, undeclared qnames."""
    from edgar_sec.engine.xbrl.taxonomy.archive import (
        bundle_namespaces,
        load_slice,
        namespace_key,
    )

    referenced = {item.concept_qname for item in own}
    facts_path = bundle_dir / "facts.parquet"
    if facts_path.is_file():
        referenced.update(
            pq.read_table(facts_path, columns=["concept_qname"])
            .column("concept_qname")
            .to_pylist()
        )
    for arcs_name in ("calculation_arcs.parquet", "presentation_arcs.parquet"):
        arcs_path = bundle_dir / arcs_name
        if arcs_path.is_file():
            arcs = pq.read_table(arcs_path, columns=["parent_qname", "child_qname"])
            referenced.update(arcs.column("parent_qname").to_pylist())
            referenced.update(arcs.column("child_qname").to_pylist())
    supplied: dict[str, ConceptDeclaration] = {}
    for prefix, uri in bundle_namespaces(bundle_dir).items():
        key = namespace_key(uri)
        if key is None:
            continue
        for declaration in load_slice(key[0], key[1]):
            qname = f"{prefix}:{declaration.name}"
            if qname in referenced and qname not in supplied:
                supplied[qname] = ConceptDeclaration(
                    concept_qname=qname,
                    name=declaration.name,
                    period_type=declaration.period_type,
                    balance=declaration.balance,
                    substitution_group=declaration.substitution_group,
                    item_type=declaration.item_type,
                    abstract=declaration.abstract,
                )
    own_qnames = {item.concept_qname for item in own}
    return tuple(
        supplied[qname] for qname in sorted(supplied) if qname not in own_qnames
    )


def declarations_from_arrow_table(table: pa.Table) -> tuple[ConceptDeclaration, ...]:
    """Rebuild concept declarations from a declarations Arrow table."""
    rows = table.to_pylist()
    return tuple(
        ConceptDeclaration(
            concept_qname=row["concept_qname"],
            name=row["name"],
            period_type=row["period_type"],
            balance=row["balance"],
            substitution_group=row["substitution_group"],
            item_type=row["item_type"],
            abstract=bool(row.get("abstract") or False),
        )
        for row in rows
    )
