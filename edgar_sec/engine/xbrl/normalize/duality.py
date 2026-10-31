"""Tag/axis duality normalizer un-flattening compound concept QNames into fact coordinates."""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.schema.models import XbrlFact, qname_local
from edgar_sec.engine.xbrl.normalize.normalization import (
    DimensionSlice,
    NormalizedFact,
    normalize_fact,
)

_CAMEL_CASE_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|[0-9]+")


@dataclass(frozen=True, slots=True)
class DualityProjection:
    """Projected semantic coordinates unflattened from a concept QName or dimensions."""

    canonical_measure: str
    dimensions: tuple[DimensionSlice, ...]
    origin: str  # always FROM_AXIS: dimensions come from filed axes only
    direction: float = 1.0
    atom: Atom | None = None
    residual_tokens: tuple[str, ...] = ()


def split_concept_tokens(concept_name: str) -> tuple[str, ...]:
    """Split a concept local name into constituent CamelCase tokens."""
    local = qname_local(concept_name)
    return tuple(_CAMEL_CASE_RE.findall(local))


def unflatten_concept_name(
    concept_qname: str,
    taxonomy: DomainTaxonomy | None = None,
) -> DualityProjection:
    """Unflatten a compound concept QName into base measure and dimensional slices."""
    tax = taxonomy or load_domain_taxonomy()
    if tax.token_lexicon is None:
        from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

        x_paths = resolve_xbrl_paths()
        lexicon = TokenLexicon.load_json(x_paths.default_token_lexicon_path)
    else:
        lexicon = tax.token_lexicon

    atom, residuals, direction, indexicals = decompose_concept(concept_qname, lexicon)
    head_def = tax.prime_head(atom.head)
    canonical_measure = (
        head_def.canonical_concept
        if (head_def and head_def.canonical_concept)
        else qname_local(concept_qname)
    )

    return DualityProjection(
        canonical_measure=canonical_measure,
        dimensions=(),
        origin="FROM_AXIS",
        direction=direction,
        atom=atom,
        residual_tokens=residuals,
    )


def project_fact_duality(
    fact: XbrlFact,
    taxonomy: DomainTaxonomy | None = None,
) -> NormalizedFact:
    """Normalize fact unifying explicit axis coordinates and name-encoded scopes."""
    tax = taxonomy or load_domain_taxonomy()
    base_norm = normalize_fact(fact, tax)

    if fact.dimensions:
        return base_norm

    proj = unflatten_concept_name(fact.concept_qname, tax)
    if (
        not proj.dimensions
        and proj.direction == 1.0
        and proj.canonical_measure == base_norm.measure_id
        and not proj.residual_tokens
    ):
        return base_norm

    val = base_norm.canonical_value
    if val is not None and proj.direction != 1.0:
        val = val * proj.direction

    return NormalizedFact(
        raw_fact=fact,
        measure_id=proj.canonical_measure,
        entity=base_norm.entity,
        time=base_norm.time,
        unit_class=base_norm.unit_class,
        canonical_value=val,
        dimensions=proj.dimensions,
        atom=proj.atom or base_norm.atom,
        residual_tokens=proj.residual_tokens or base_norm.residual_tokens,
    )
