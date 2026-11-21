"""Frame-to-atom resolution: a frame's concept at its corpus coordinate.

The declaration is found by exact name in the taxonomy archive slice and
the coordinate is the concept machinery's tokenization of that declared
concept; no name string is ever searched for meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.solve.concept_table import build_concept_table
from edgar_sec.engine.xbrl.taxonomy.archive import (
    CURRENT_SLICES,
    TAXONOMY_PREFIXES,
    load_slice,
    slice_versions,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy


@dataclass(frozen=True, slots=True)
class FrameCoordinate:
    """One frame concept resolved to the atom coordinate the corpus uses."""

    taxonomy: str
    tag: str
    qname: str
    slice_version: str
    declaration: ConceptDeclaration
    atom: Atom
    presumed_atom: Atom


def _slice_version(taxonomy: str, version: str | None) -> str | None:
    if version is not None:
        return version
    for slice_taxonomy, slice_version in CURRENT_SLICES:
        if slice_taxonomy == taxonomy:
            return slice_version
    versions = slice_versions(taxonomy)
    return versions[-1] if versions else None


def resolve_frame_coordinate(
    taxonomy: str,
    tag: str,
    *,
    version: str | None = None,
    domain_taxonomy: DomainTaxonomy | None = None,
) -> FrameCoordinate | None:
    """Resolve a frame's (taxonomy, tag) to its atom coordinate, or None.

    None when the taxonomy is unarchived or the tag is not declared in the
    resolved slice: an undeclared frame concept has no corpus coordinate.
    """
    prefix = TAXONOMY_PREFIXES.get(taxonomy)
    if prefix is None:
        return None
    slice_version = _slice_version(taxonomy, version)
    if slice_version is None:
        return None
    declarations = {
        declaration.name: declaration
        for declaration in load_slice(taxonomy, slice_version)
    }
    declaration = declarations.get(tag)
    if declaration is None:
        return None
    qname = f"{prefix}:{tag}"
    table = build_concept_table(
        domain_taxonomy or load_domain_taxonomy(),
        (qname,),
        declarations=(declaration,),
    )
    record = table.record(qname)
    return FrameCoordinate(
        taxonomy=taxonomy,
        tag=tag,
        qname=qname,
        slice_version=slice_version,
        declaration=declaration,
        atom=record.atom,
        presumed_atom=record.presumed_atom,
    )


__all__ = ["FrameCoordinate", "resolve_frame_coordinate"]
