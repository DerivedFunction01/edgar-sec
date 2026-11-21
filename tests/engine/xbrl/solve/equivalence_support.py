"""Shared atom helpers for the equivalence test modules."""

from __future__ import annotations

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import presumed_atom
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _atom(qname: str) -> Atom:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(qname, tax.token_lexicon)
    return atom


def _defaults():
    """The shipped defaults table, loaded through the domain taxonomy."""
    return load_domain_taxonomy().default_coordinates


def _scoped_portion_group():
    """A synthetic TAX_PORTION-shaped group: scoped to the tax-expense frame."""
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
        ScopeContext,
        SiblingGroup,
    )

    return SiblingGroup(
        "TAX_PORTION",
        ("M_CURRENT", "M_DEFERRED"),
        "compoundable",
        scope=(
            ScopeContext(
                heads=("H_EXPENSE",),
                shared_modifiers=("M_TAX",),
                shared_exact=True,
            ),
            ScopeContext(
                heads=("H_INCOME",),
                shared_modifiers=("M_RECONCILIATION", "M_TAX_INCOME"),
            ),
        ),
    )


def _typed_atom(qname: str, item_type: str) -> Atom:
    from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
    from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer

    declaration = ConceptDeclaration(
        concept_qname=qname, name=qname.partition(":")[2], item_type=item_type
    )
    return ConceptTokenizer(load_domain_taxonomy()).tokenize(qname, declaration).atom


def _presumed_ladder(atom: Atom, derived: str | None, placement: str | None) -> Atom:
    """Full ladder composition: filing-local rung, then the global default."""
    from edgar_sec.engine.xbrl.solve.equivalence import presumed_atom_filing_local

    return presumed_atom(
        presumed_atom_filing_local(atom, derived, placement), _defaults()
    )
