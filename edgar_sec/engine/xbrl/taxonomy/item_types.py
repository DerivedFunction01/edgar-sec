"""Standard-namespace item types: a derived table merged under extension declarations."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping

from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration

if TYPE_CHECKING:
    from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


@dataclasses.dataclass(frozen=True, slots=True)
class TextCoordinateRule:
    """The modifier a declared item type asserts, and the types that assert it."""

    modifier_id: str
    item_types: frozenset[str]


def text_coordinate_rule(taxonomy: DomainTaxonomy) -> TextCoordinateRule | None:
    """Resolve the text-coordinate rule from the def declaring asserted types."""
    for modifier in taxonomy.subatomic_modifiers:
        if modifier.asserted_item_types:
            return TextCoordinateRule(
                modifier_id=modifier.modifier_id,
                item_types=frozenset(modifier.asserted_item_types),
            )
    return None


def load_standard_item_types(path: Path | str) -> dict[str, str]:
    """Load the derived qname -> item-type table for standard namespaces."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(qname): str(item_type) for qname, item_type in data.items()}


def item_type_local(item_type: str | None) -> str | None:
    """Local part of an item-type QName (prefixes carry no family meaning)."""
    if item_type is None:
        return None
    return item_type.rsplit(":", 1)[-1]


def merge_declarations(
    declarations: Iterable[ConceptDeclaration],
    table: Mapping[str, str],
) -> tuple[ConceptDeclaration, ...]:
    """Fill missing item types from the standard table; declarations win."""
    merged: list[ConceptDeclaration] = []
    for declaration in declarations:
        if declaration.item_type is None:
            item_type = table.get(declaration.concept_qname)
            if item_type is not None:
                declaration = dataclasses.replace(declaration, item_type=item_type)
        merged.append(declaration)
    return tuple(merged)


def declaration_for(
    qname: str,
    table: Mapping[str, str],
    declarations: Iterable[ConceptDeclaration]
    | Mapping[str, ConceptDeclaration] = (),
) -> ConceptDeclaration | None:
    """Effective declaration for a qname: extension first, table underneath."""
    if isinstance(declarations, Mapping):
        found = declarations.get(qname)
        declarations = (found,) if found is not None else ()
    for declaration in declarations:
        if declaration.concept_qname == qname:
            if declaration.item_type is None and qname in table:
                return dataclasses.replace(declaration, item_type=table[qname])
            return declaration
    item_type = table.get(qname)
    if item_type is None:
        return None
    return ConceptDeclaration(
        concept_qname=qname,
        name=qname.partition(":")[2],
        item_type=item_type,
    )
