"""Precision veto pass: set-level refusals over gate-final
claims for the priced precision packets. Tokens come from
the shared home tokenizer; legs are the census-priced sets.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from edgar_sec.engine.tables.extraction.core.text.normalize import (
    normalize_text,
)
from edgar_sec.engine.tables.extraction.form_specs.core_form_specs import (
    INTANGIBLES_LEXICON,
)
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_specs import (
    DERIV_FAMILY,
    DERIV_HEADER_LEVEL_TOKEN,
    DERIV_HEADER_SECURITIES_TOKEN,
    DERIV_LEAD_TOKEN,
    DERIV_STUB_TOKEN,
    CREDIT_DOMINANCE_MARGIN,
    CREDIT_FAMILY,
    CREDIT_LOSSES_CORE,
    DT_FAMILY,
    DT_STUB_BIGRAM,
    DT_PPA_PHRASES,
    DT_SCHEDULE_II_PHRASE,
    DT_UTB_SUBJECT_PHRASE,
    LEG_DT_NONCOMPOSITION,
    LEG_DT_NO_SUBJECT,
    LEG_DT_PPA_FORM,
    LEG_DT_PROVISION_FORM,
    LEG_DT_SCHEDULE_II,
    LEG_DT_TOTALS_ONLY,
    LEG_DT_UTB_SUBJECT,
    DT_VALUATION_ALLOWANCE_BIGRAM,
    EPS_ADJUSTMENT_TOKENS,
    EPS_FACE_STATEMENT_PHRASES,
    EPS_FAMILY,
    EPS_NON_OWN_CHANNELS,
    EPS_RECONCILIATION_CORE,
    EPS_RESTATEMENT_TOKENS,
    GOODWILL_FAMILY,
    INT_COMPOSITION_FAILED_DETAIL,
    INT_FAMILY,
    INV_FAMILY,
    INV_LEAD_INVENTORY_TOKEN,
    INV_LEAD_TABLES_TOKEN,
    LABOR_EIN_PREFIX,
    LABOR_EIN_TOKEN,
    LABOR_FAMILY,
    LABOR_FORM_PHRASES,
    LEG_CONTEXT_ONLY,
    LEG_CREDIT_LOSSES_HOST,
    LEG_DOMINANT_CO_CLAIM,
    LEG_EMPLOYER_FORM,
    LEG_EPS_HOST_ABSENT,
    LEG_GOODWILL_HOST,
    LEG_HEADER_LEVEL,
    LEG_HEADER_SECURITIES,
    LEG_LEAD_CONVERTIBLE,
    LEG_LEAD_INVENTORY,
    LEG_LEAD_TABLES,
    LEG_PCT_ROWS,
    LEG_RESTATEMENT_FACE_STATEMENT,
    LEG_STUB_BIGRAM,
    LEG_STUB_CREDIT,
    TOKEN_STOPLIST,
    DEBT_HEADER_YEAR_MAX,
    DEBT_HEADER_YEAR_MIN,
    DEBT_NUMERIC_CELLS_MAX,
    LEG_LEADIN_ONLY,
)
from edgar_sec.foundation.text.date_patterns import (
    FULL_DATE_STUB_RE,
    MONTH_NAMES,
    YEAR_TOKEN_SEARCH_RE,
)
from edgar_sec.foundation.text.dates import parse_date
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


def _deriv_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
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


_DT_MONTH_STARTS = tuple(name.lower() for name in MONTH_NAMES)
_DT_PERIOD_PHRASES = (
    "year ended",
    "years ended",
    "as of",
    "for the year",
    "for the period",
)
_DT_TAX_EXPENSE_RE = re.compile(r"(income )?tax(es)? (expense|benefit)")
_DT_AMOUNT_ONLY_RE = re.compile(r"[\d,().$%\s-]+")
_DT_WORD_SPLIT_RE = re.compile(r"[^a-z]+")
_DT_HEADER_WORDS = frozenset(
    {
        "deferred",
        "tax",
        "income",
        "assets",
        "asset",
        "liabilities",
        "liability",
        "current",
        "noncurrent",
        "taxes",
        "attributable",
        "to",
    }
)


def _dt_stub_lines(geometry) -> list[str]:
    """Normalized stub lines of the geometry, in order."""
    return [normalize_text(stub) for stub in geometry.stubs or ()]


def _dt_is_date_line(text: str) -> bool:
    """A stub line that is a date or period fragment, read
    through the foundation date home."""
    if parse_date(text) is not None or FULL_DATE_STUB_RE.match(text):
        return True
    if any(text == m or text.startswith(m + " ") for m in _DT_MONTH_STARTS):
        return True
    if YEAR_TOKEN_SEARCH_RE.search(text) and len(text) <= 12:
        return True
    return any(phrase in text for phrase in _DT_PERIOD_PHRASES)


def _dt_is_header_line(text: str) -> bool:
    """A subject/header line: only deferred-tax vocabulary words."""
    words = [w for w in _DT_WORD_SPLIT_RE.split(text) if w]
    return bool(words) and all(w in _DT_HEADER_WORDS for w in words)


def _dt_component_stubs(geometry) -> list[str]:
    """Hygienic component stubs: stub lines that are component
    captions, excluding subject headers, date lines, valuation
    allowance, total/net/gross and classification lines."""
    kept = []
    for text in _dt_stub_lines(geometry):
        if not text or _dt_is_date_line(text) or _dt_is_header_line(text):
            continue
        if "valuation allowance" in text:
            continue
        if "total" in text or "subtotal" in text or "gross deferred" in text:
            continue
        if "net" in text.split() and "deferred" in text:
            continue
        if text.startswith("less"):
            continue
        if "current" in text and "deferred" in text:
            continue
        if (
            _DT_TAX_EXPENSE_RE.search(text)
            and "carryforward" not in text
            and "credit" not in text
        ):
            continue
        if _DT_AMOUNT_ONLY_RE.fullmatch(text):
            continue
        kept.append(text)
    return kept


def _dt_va_movement_form(geometry) -> bool:
    """The S3 member form: a valuation-allowance movement
    schedule (balance/additions/deductions movement lines)."""
    text = " || ".join(_dt_stub_lines(geometry))
    if "valuation allowance" not in text:
        return False
    return (
        "balance at beginning" in text
        or "beginning balance" in text
        or ("additions" in text and "deductions" in text)
    )


def _dt_combo_legs(geometry, tokens) -> list[str]:
    """DT-2 (packet DT-COMBO): the composition condition and
    the priced form tests, over the geometry's stubs/headers."""
    legs = []
    stubs = _dt_stub_lines(geometry)
    stub_text = " || ".join(stubs)
    kept = _dt_component_stubs(geometry)
    if not _dt_va_movement_form(geometry) and len(set(kept)) < 2:
        legs.append(LEG_DT_NONCOMPOSITION)
    if kept and all(("current" in k or "noncurrent" in k) for k in kept):
        legs.append(LEG_DT_TOTALS_ONLY)
    if any(phrase in stub_text for phrase in DT_PPA_PHRASES):
        legs.append(LEG_DT_PPA_FORM)
    if (
        kept
        and len(kept) <= 3
        and all(("tax expense" in k or "tax benefit" in k) for k in kept)
    ):
        legs.append(LEG_DT_PROVISION_FORM)
    if (
        kept
        and DT_UTB_SUBJECT_PHRASE in kept[0]
        and sum(
            1
            for k in kept
            if "unrecognized" in k or "positions taken" in k or "settlements" in k
        )
        >= len(kept) / 2
    ):
        legs.append(LEG_DT_UTB_SUBJECT)
    header_text = " || ".join(normalize_text(h) for h in geometry.headers or ())
    if "deferred tax" not in stub_text and "deferred tax" not in header_text:
        legs.append(LEG_DT_NO_SUBJECT)
    if DT_SCHEDULE_II_PHRASE in header_text or DT_SCHEDULE_II_PHRASE in stub_text:
        legs.append(LEG_DT_SCHEDULE_II)
    return legs


def _deferred_tax_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """DT-1: percentage rows, eps host absence, or the bigram."""
    legs = []
    if geometry.pct_row_share > 0:
        legs.append(LEG_PCT_ROWS)
    if not _host_present(tokens, EPS_RECONCILIATION_CORE):
        if DT_VALUATION_ALLOWANCE_BIGRAM not in tokens.bigrams:
            legs.append(LEG_EPS_HOST_ABSENT)
    if DT_STUB_BIGRAM in tokens.bigrams:
        legs.append(LEG_STUB_BIGRAM)
    legs.extend(_dt_combo_legs(geometry, tokens))
    return tuple(legs)


def _inventory_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """INV-1: credit-losses host content or lead naming."""
    legs = []
    if _host_present(tokens, CREDIT_LOSSES_CORE):
        legs.append(LEG_CREDIT_LOSSES_HOST)
    if INV_LEAD_TABLES_TOKEN in tokens.lead:
        legs.append(LEG_LEAD_TABLES)
    if INV_LEAD_INVENTORY_TOKEN in tokens.lead:
        legs.append(LEG_LEAD_INVENTORY)
    return tuple(legs)


def _credit_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """Credit dominance: a co-claim outscoring credit by the margin."""
    score = result.scores.get(CREDIT_FAMILY)
    if score is None:
        return ()
    strongest = max(
        (
            result.scores[family].total
            for family in result.claims
            if family != CREDIT_FAMILY and family in result.scores
        ),
        default=None,
    )
    if strongest is not None and strongest >= score.total + CREDIT_DOMINANCE_MARGIN:
        return (LEG_DOMINANT_CO_CLAIM,)
    return ()


def _composition_failed(score) -> bool:
    """The recorded composition failure in a score's trail."""
    return any(
        entry.channel == "form_test" and entry.detail == INT_COMPOSITION_FAILED_DETAIL
        for entry in score.evidence
    )


def _has_class_stub(geometry) -> bool:
    """An intangibles class term in the geometry's stubs."""
    text = " || ".join({normalize_text(stub) for stub in geometry.stubs})
    return any(term in text for term in INTANGIBLES_LEXICON)


def _intangibles_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """F1: a goodwill walk claimed on note-context mass."""
    score = result.scores.get(INT_FAMILY)
    if score is None:
        return ()
    if not any(group.family == GOODWILL_FAMILY for group in result.groups):
        return ()
    if not _composition_failed(score):
        return ()
    if _has_class_stub(geometry):
        return ()
    return (LEG_GOODWILL_HOST,)


def eps_restatement_face_fires(geometry) -> bool:
    """EPS-P1: the header token set carries the restatement-
    adjustment columns and a face statement is named in the
    header/stub text."""
    tokens = frozenset(normalize_text(" ".join(geometry.headers)).split())
    if not any(token in tokens for token in EPS_ADJUSTMENT_TOKENS):
        return False
    if not all(token in tokens for token in EPS_RESTATEMENT_TOKENS):
        return False
    text = normalize_text(" ".join([*geometry.headers, *geometry.stubs]))
    return any(phrase in text for phrase in EPS_FACE_STATEMENT_PHRASES)


def eps_context_only_fires(result) -> bool:
    """EPS-P2: the eps score carries no positive own-text
    channel mass; every positive channel is context or veto."""
    score = result.scores.get(EPS_FAMILY)
    if score is None:
        return False
    own = sum(
        value
        for channel, value in score.by_channel.items()
        if channel not in EPS_NON_OWN_CHANNELS and value > 0
    )
    return own <= 0.0


def _eps_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """EPS-P: the restatement face-statement leg, then the
    context-only leg, in priced order."""
    legs = []
    if eps_restatement_face_fires(geometry):
        legs.append(LEG_RESTATEMENT_FACE_STATEMENT)
    if eps_context_only_fires(result):
        legs.append(LEG_CONTEXT_ONLY)
    return tuple(legs)


def _labor_legs(geometry, tokens: ChannelTokens, result) -> tuple[str, ...]:
    """Labor: the multiemployer-plan form signature, read
    from the geometry's headers directly."""
    for header in geometry.headers or ():
        text = normalize_text(header)
        if LABOR_EIN_TOKEN in text.split() or LABOR_EIN_PREFIX in text:
            return (LEG_EMPLOYER_FORM,)
        if any(phrase in text for phrase in LABOR_FORM_PHRASES):
            return (LEG_EMPLOYER_FORM,)
    return ()


_LEG_EVALUATORS = {
    DERIV_FAMILY: _deriv_legs,
    DT_FAMILY: _deferred_tax_legs,
    INV_FAMILY: _inventory_legs,
    INT_FAMILY: _intangibles_legs,
    CREDIT_FAMILY: _credit_legs,
    LABOR_FAMILY: _labor_legs,
    EPS_FAMILY: _eps_legs,
}


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
    family: str, geometry, tokens: ChannelTokens, result, own_score=None
) -> tuple[str, ...]:
    if family == DEBT_FAMILY:
        return _debt_legs(
            geometry,
            own_score if own_score is not None else result.scores.get(family),
        )
    evaluator = _LEG_EVALUATORS.get(family)
    return evaluator(geometry, tokens, result) if evaluator is not None else ()


def apply_precision_vetoes(geometries, results, stages=None):
    """Final pass: remove packet-family claims firing any leg.

    Firings read the input results only, except the debt
    leg, whose own-score reads the captured claim stages
    when they are given, so removals never change another
    firing.
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
            if tokens is None:
                tokens = channel_tokens(geometries[index])
            own_score = (
                stages[index].scores.get(family)
                if stages is not None
                else result.scores.get(family)
            )
            legs = _fired_legs(family, geometries[index], tokens, result, own_score)
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
