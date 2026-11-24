"""Precision veto pass: set-level refusals over gate-final
claims for the Round-3 precision packets. Tokens come from
the shared home tokenizer; legs are the census-priced sets;
the debt leg reads the claim's captured own-stage record.
"""

from __future__ import annotations

from typing import NamedTuple

from edgar_sec.engine.tables.extraction.core.text.normalize import (
    normalize_text,
)
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_specs import (
    DEBT_FAMILY,
    DEBT_HEADER_YEAR_MAX,
    DEBT_HEADER_YEAR_MIN,
    DEBT_NUMERIC_CELLS_MAX,
    DERIV_FAMILY,
    DERIV_HEADER_LEVEL_TOKEN,
    DERIV_HEADER_SECURITIES_TOKEN,
    DERIV_LEAD_TOKEN,
    DERIV_STUB_TOKEN,
    CREDIT_LOSSES_CORE,
    DT_FAMILY,
    DT_STUB_BIGRAM,
    EPS_RECONCILIATION_CORE,
    INV_FAMILY,
    INV_LEAD_INVENTORY_TOKEN,
    INV_LEAD_TABLES_TOKEN,
    LEG_CREDIT_LOSSES_HOST,
    LEG_EPS_HOST_ABSENT,
    LEG_HEADER_LEVEL,
    LEG_HEADER_SECURITIES,
    LEG_LEADIN_ONLY,
    LEG_LEAD_CONVERTIBLE,
    LEG_LEAD_INVENTORY,
    LEG_LEAD_TABLES,
    LEG_PCT_ROWS,
    LEG_STUB_BIGRAM,
    LEG_STUB_CREDIT,
    TOKEN_STOPLIST,
)
from edgar_sec.foundation.text.normalize import collapse_whitespace
from edgar_sec.foundation.text.words import word_tokens


def _token_list(text: str) -> list[str]:
    """Word tokens in order, from the shared home tokenizer."""
    return word_tokens(collapse_whitespace(text or ""))


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_token_list(text))


class ChannelTokens(NamedTuple):
    """One geometry's priced token sets, by channel."""

    lead: frozenset[str]
    header: frozenset[str]
    stub: frozenset[str]
    grid: frozenset[str]
    bigrams: frozenset[str]


def channel_tokens(geometry) -> ChannelTokens:
    """Token sets for the lead, header, stub, and grid channels."""
    lead_text = " ".join(
        (
            geometry.caption,
            geometry.leadin,
            geometry.notehead,
            geometry.lead_title,
            geometry.lead,
        )
    )
    bigrams = set()
    for line in geometry.stubs:
        line_tokens = _token_list(line)
        bigrams.update(
            f"{a} {b}" for a, b in zip(line_tokens, line_tokens[1:], strict=False)
        )
    return ChannelTokens(
        lead=_tokens(lead_text) - TOKEN_STOPLIST,
        header=_tokens(" ".join(geometry.headers)) - TOKEN_STOPLIST,
        stub=_tokens(" ".join(geometry.stubs)),
        grid=_tokens(geometry.grid_text),
        bigrams=frozenset(bigrams),
    )


def _host_present(tokens: ChannelTokens, core: frozenset[str]) -> bool:
    """A host family's core term in the stub or grid tokens."""
    return any(term in tokens.stub or term in tokens.grid for term in core)


def _deriv_legs(geometry, tokens: ChannelTokens) -> tuple[str, ...]:
    """DERIV-1: impostor vocabulary naming the neighbour note."""
    legs = []
    if DERIV_LEAD_TOKEN in tokens.lead:
        legs.append(LEG_LEAD_CONVERTIBLE)
    if DERIV_HEADER_SECURITIES_TOKEN in tokens.header:
        legs.append(LEG_HEADER_SECURITIES)
    if DERIV_STUB_TOKEN in tokens.stub:
        legs.append(LEG_STUB_CREDIT)
    if DERIV_HEADER_LEVEL_TOKEN in tokens.header:
        legs.append(LEG_HEADER_LEVEL)
    return tuple(legs)


def _deferred_tax_legs(geometry, tokens: ChannelTokens) -> tuple[str, ...]:
    """DT-1: percentage rows, eps host absence, or the bigram."""
    legs = []
    if geometry.pct_row_share > 0:
        legs.append(LEG_PCT_ROWS)
    if not _host_present(tokens, EPS_RECONCILIATION_CORE):
        legs.append(LEG_EPS_HOST_ABSENT)
    if DT_STUB_BIGRAM in tokens.bigrams:
        legs.append(LEG_STUB_BIGRAM)
    return tuple(legs)


def _inventory_legs(geometry, tokens: ChannelTokens) -> tuple[str, ...]:
    """INV-1: credit-losses host content or lead naming."""
    legs = []
    if _host_present(tokens, CREDIT_LOSSES_CORE):
        legs.append(LEG_CREDIT_LOSSES_HOST)
    if INV_LEAD_TABLES_TOKEN in tokens.lead:
        legs.append(LEG_LEAD_TABLES)
    if INV_LEAD_INVENTORY_TOKEN in tokens.lead:
        legs.append(LEG_LEAD_INVENTORY)
    return tuple(legs)


def _is_year_token(text: str) -> bool:
    """A 4-digit year token inside the priced header window."""
    return (
        text.isdigit()
        and len(text) == 4
        and DEBT_HEADER_YEAR_MIN <= int(text) <= DEBT_HEADER_YEAR_MAX
    )


def _is_numeric_token(text: str) -> bool:
    """A header cell that parses as a number (marks stripped)."""
    cleaned = text.replace(",", "").replace("$", "").replace("%", "")
    cleaned = cleaned.strip("()")
    try:
        float(cleaned)
    except ValueError:
        return False
    return True


def _header_year_amount_pair(headers) -> bool:
    """A year header cell immediately followed by a numeric,
    non-year header cell: the flattened vertical form."""
    cells = [str(header).strip() for header in headers]
    return any(
        _is_year_token(cells[index])
        and not _is_year_token(cells[index + 1])
        and _is_numeric_token(cells[index + 1])
        for index in range(len(cells) - 1)
    )


def _year_stub_present(geometry) -> bool:
    """A 4-digit-year stub or a thereafter stub."""
    for stub in geometry.stubs:
        text = str(stub).strip()
        if text.isdigit() and len(text) == 4:
            return True
        if "thereafter" in normalize_text(stub):
            return True
    return False


def _ladder_passed(score) -> bool:
    """The own-stage year-ladder form test passed."""
    return any(
        entry.channel == "form_test" and "year_ladder passed" in entry.detail
        for entry in score.evidence
    )


def _debt_legs(geometry, own_score) -> tuple[str, ...]:
    """DEBT-P9: leadin-only own support, no maturity-year rows,
    no flattened year headers, numeric mass at the cap."""
    if own_score is None:
        return ()
    channels = own_score.by_channel
    if channels.get("leadin", 0.0) <= 0.0:
        return ()
    if channels.get("admission", 0.0) > 0.0:
        return ()
    if _ladder_passed(own_score):
        return ()
    if _year_stub_present(geometry):
        return ()
    if geometry.numeric_cells > DEBT_NUMERIC_CELLS_MAX:
        return ()
    if _header_year_amount_pair(geometry.headers):
        return ()
    return (LEG_LEADIN_ONLY,)


_LEG_EVALUATORS = {
    DERIV_FAMILY: _deriv_legs,
    DT_FAMILY: _deferred_tax_legs,
    INV_FAMILY: _inventory_legs,
}


def _fired_legs(
    family: str, geometry, tokens: ChannelTokens | None, own_score
) -> tuple[str, ...]:
    if family == DEBT_FAMILY:
        return _debt_legs(geometry, own_score)
    evaluator = _LEG_EVALUATORS.get(family)
    return evaluator(geometry, tokens) if evaluator is not None else ()


def apply_precision_vetoes(geometries, results, stages):
    """Final pass: remove packet-family claims firing any leg.

    Firings read the input results and the captured claim
    stages only, so removals never change another firing.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    fired = {}
    for index, result in enumerate(results):
        tokens = None
        for family in result.claims:
            if family != DEBT_FAMILY and family not in _LEG_EVALUATORS:
                continue
            own_score = stages[index].scores.get(family)
            if family in _LEG_EVALUATORS:
                if tokens is None:
                    tokens = channel_tokens(geometries[index])
            legs = _fired_legs(family, geometries[index], tokens, own_score)
            if legs:
                fired[(index, family)] = legs
    if not fired:
        return list(results)
    out = []
    for index, result in enumerate(results):
        hit = {fam: legs for (i, fam), legs in fired.items() if i == index}
        if not hit:
            out.append(result)
            continue
        scores = dict(result.scores)
        for family, legs in hit.items():
            score = scores.get(family)
            if score is not None:
                detail = "precision veto: " + ", ".join(legs)
                scores[family] = FamilyScore(
                    score.family,
                    score.total,
                    dict(score.by_channel),
                    score.evidence + (ClaimEvidence("gate", detail, 0.0),),
                )
        out.append(
            CompetitionResult(
                claims=tuple(f for f in result.claims if f not in hit),
                contested=tuple(f for f in result.contested if f not in hit),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=tuple(g for g in result.groups if g.family not in hit),
            )
        )
    return out
