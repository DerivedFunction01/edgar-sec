"""Consolidated universal DRY combinator engine for derivative instruments."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.domain.taxonomy.schedules.derivatives.bases import (
    CONTRACT_SUFFIXES,
    UNIVERSAL_BASES,
)
from edgar_sec.foundation.text.compounds import (
    expand_compounds,
    expand_variants,
)


def build_derivative_grammar(
    underlyings: Sequence[str | None] | str,
    bases: Sequence[str | None] | str = UNIVERSAL_BASES,
    suffixes: Sequence[str | None] | str | None = CONTRACT_SUFFIXES,
    *,
    optional_suffix: bool = True,
    auto_plural: bool = True,
) -> tuple[str, ...]:
    """Generate every ``<Underlying> <Base> [<Suffix>]`` combination, deduplicated longest-first.

    ``optional_suffix`` adds the bare form as well; ``auto_plural`` expands each component
    to its singular and plural.
    """
    expanded_underlyings = expand_variants(underlyings) if auto_plural else underlyings
    expanded_bases = expand_variants(bases) if auto_plural else bases

    suffix_slot: tuple[str | None, ...] | None = None
    if suffixes is not None:
        expanded_suffixes = expand_variants(suffixes) if auto_plural else suffixes
        if isinstance(expanded_suffixes, str):
            expanded_suffixes = (expanded_suffixes,)
        suffix_slot = (
            (None, *expanded_suffixes) if optional_suffix else expanded_suffixes
        )

    return expand_compounds(expanded_underlyings, expanded_bases, suffix_slot)


def build_pay_receive_swaps() -> tuple[str, ...]:
    """Generates pay/receive fixed and floating rate swap combinations."""
    pay_receive_prefixes = (
        "pay fixed receive floating",
        "pay-fixed receive-floating",
        "pay floating receive fixed",
        "pay-floating receive-fixed",
        "pay fixed",
        "pay-fixed",
        "pay floating",
        "pay-floating",
        "receive fixed",
        "receive-fixed",
        "receive floating",
        "receive-floating",
    )
    return expand_compounds(
        pay_receive_prefixes,
        expand_variants(("swap", "interest rate swap")),
    )
