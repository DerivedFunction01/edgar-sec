"""Semantic and context keys over filing facts for the counter-solver."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.models import XbrlFact, qname_local


_ContextKey = tuple[object, ...]
_SemanticKey = tuple[str, _ContextKey, float]
_Resolution = tuple[float, frozenset[_SemanticKey], bool, float]
_FinerEntry = tuple[str, _ContextKey, float, frozenset]
_FinerIndex = dict[_ContextKey, list[_FinerEntry]]


def _precision_tolerance(fact: XbrlFact) -> float:
    """Half the fact's last filed digit; a missing decimals gets the flat floor."""
    if fact.decimals is None:
        return 0.0001
    return 0.5 * (10.0 ** (-fact.decimals))


def _context_key(fact: XbrlFact) -> _ContextKey:
    return (
        str(fact.accession),
        fact.period_type,
        fact.instant_date,
        fact.start_date,
        fact.end_date,
        fact.unit,
        tuple(sorted(fact.dimensions.items())),
    )


def _semantic_key(fact: XbrlFact) -> _SemanticKey:
    return (fact.concept_qname, _context_key(fact), float(fact.value))


def _local_name(qname: str) -> str:
    return qname_local(qname)
