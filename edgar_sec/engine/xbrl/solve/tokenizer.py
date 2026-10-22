"""Tokenizer service: qname in, atom + provenance + ranked equivalents out."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept_expression,
    residual_counts,
)
from edgar_sec.engine.xbrl.normalize.lexicon import LexiconMatch
from edgar_sec.engine.xbrl.normalize.temporal import TemporalInterval
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.solve.equivalence import (
    RankedEquivalent,
    presumed_atom,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.engine.xbrl.taxonomy.item_types import text_coordinate_rule


@dataclass(frozen=True, slots=True)
class TokenizedFact:
    """One concept's full decomposition record over a domain taxonomy."""

    qname: str
    atom: Atom
    presumed_atom: Atom
    residuals: tuple[str, ...] = ()
    indexicals: tuple[str, ...] = ()
    derived_horizon: str | None = None
    temporal: TemporalInterval | None = None
    operator: str | None = None
    operands: tuple[Atom, ...] = ()
    relations: tuple[tuple[str, Atom], ...] = ()
    direction: float = 1.0
    matches: tuple[LexiconMatch, ...] = ()


class ConceptTokenizer:
    """Decomposition and equivalence ranking bound to one taxonomy."""

    def __init__(self, taxonomy: DomainTaxonomy) -> None:
        """Bind the taxonomy's lexicon, defaults, and declared groups."""
        if taxonomy.token_lexicon is None:
            raise ValueError("ConceptTokenizer requires a token lexicon.")
        self._taxonomy = taxonomy
        self._sibling_groups = tuple(taxonomy.sibling_groups) or None
        self._text_rule = text_coordinate_rule(taxonomy)

    def tokenize(
        self, qname: str, declaration: ConceptDeclaration | None = None
    ) -> TokenizedFact:
        """Decompose a concept qname into its full tokenized record.

        The presumed atom applies declared defaults for classification
        only; the record's atom is the decomposition as stated.
        """
        lexicon = self._taxonomy.token_lexicon
        assert lexicon is not None
        expression = decompose_concept_expression(
            qname, lexicon, declaration, self._text_rule
        )
        presumed = presumed_atom(
            expression.atom,
            self._taxonomy.default_coordinates,
            self._sibling_groups,
        )
        return TokenizedFact(
            qname=qname,
            atom=expression.atom,
            presumed_atom=presumed,
            residuals=expression.residuals,
            indexicals=expression.indexicals,
            derived_horizon=expression.derived_horizon,
            temporal=expression.temporal,
            operator=expression.operator,
            operands=expression.operands,
            relations=expression.relations,
            direction=expression.direction,
            matches=expression.matches,
        )

    def equivalents(
        self,
        target: str | Atom,
        candidates: Iterable[tuple[str, Atom] | str],
        declaration: ConceptDeclaration | None = None,
    ) -> tuple[RankedEquivalent, ...]:
        """Rank candidates against a qname or atom target."""
        if isinstance(target, str):
            target_qname = target
            target_atom = self.tokenize(target, declaration).atom
        else:
            target_qname = ""
            target_atom = target
        pool = []
        counts = {}
        for item in candidates:
            if isinstance(item, str):
                record = self.tokenize(item)
                pool.append((item, record.atom))
                counts[item] = residual_counts(record.residuals)
            else:
                qname, atom = item
                pool.append((qname, atom))
                counts[qname] = residual_counts(self.tokenize(qname).residuals)
        return rank_equivalents(
            target_qname,
            target_atom,
            tuple(pool),
            self._taxonomy.default_coordinates,
            sibling_groups=self._sibling_groups,
            residual_counts=counts,
        )
