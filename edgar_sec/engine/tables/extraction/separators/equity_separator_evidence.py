"""Equity-statement separator evidence (TEST_EQUITY_SEPARATOR).

The routed elimination cascade over one equity candidate: the
dated-balance bookend core gate and the priced claim-local
legs; the filing-level assignment pass reads the same features.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.foundation.text.date_patterns import (
    MONTH_NAMES,
    STRICT_MONTH_PATTERN,
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_SEARCH_RE,
)
from edgar_sec.engine.tables.extraction.separators.equity_separator_specs import (
    EQUITY_SEPARATOR_SPECS,
    EquitySeparatorSpec,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys,
    norm,
    stub_key,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    HEADER_STOP_TOKENS,
)
from edgar_sec.engine.tables.extraction.seats.specs.seat_test_specs import (
    SEAT_TEST_SPECS_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.seats.statement_seat import _column_walk

_HEADER_LINES = 3
_YEAR_RE = YEAR_TOKEN_SEARCH_RE

_DATE_ONLY_RE = re.compile(
    rf"^(?:{STRICT_MONTH_PATTERN})\s+\d{{1,2}},\s+(?:{YEAR_TOKEN_PATTERN})$",
    re.IGNORECASE,
)

_TEXT_INDEX = TermIndex(
    [TermEntry(name, "month") for name in MONTH_NAMES]
    + [
        TermEntry("balance", "balance"),
        TermEntry("beginning", "beginning"),
        TermEntry("end of", "end_of"),
    ]
    + [
        TermEntry(phrase, "period")
        for phrase in (
            "beginning of period",
            "end of period",
            "beginning of year",
            "end of year",
        )
    ]
)

_SEP = "\x00"


@lru_cache(maxsize=None)
def _spec_index(spec) -> TermIndex:
    """The spec's keyed entries on the term-index home: exact
    kinds fold the key separator in, prefix kinds lead with it."""
    entries: list[TermEntry] = []

    def exact(terms, kind):
        entries.extend(TermEntry(f"{_SEP}{t}{_SEP}", kind, value=t) for t in terms)

    def prefix(terms, kind):
        entries.extend(TermEntry(f"{_SEP}{t}", kind, value=t) for t in terms)

    exact(spec.stub_keys, "stub_key")
    exact(spec.header_tokens, "header_token")
    exact(spec.flow_stub_keys, "flow_key")
    exact(spec.core_vocab, "core_vocab")
    prefix(spec.component_keys, "component_key")
    exact(spec.component_header_tokens, "component_header")
    prefix((spec.flow_prefix,), "flow_prefix")
    exact(("total",), "total_key")
    return TermIndex(entries)


def _key_scans(spec, stub_keys, header_keys_):
    """One index pass per key surface: kind -> terms present."""
    index = _spec_index(spec)
    stub_surface = _SEP + _SEP.join(sorted(stub_keys)) + _SEP if stub_keys else ""
    header_surface = (
        _SEP + _SEP.join(sorted(header_keys_)) + _SEP if header_keys_ else ""
    )
    return index.scan(stub_surface), index.scan(header_surface)


def _dated_balance_count(raw_stubs) -> int:
    """Stub rows naming a balance together with a date."""
    count = 0
    for stub in raw_stubs:
        lowered = (stub or "").lower()
        if _DATE_ONLY_RE.match(lowered.strip()):
            count += 1
            continue
        if "balance" not in lowered and "net assets" not in lowered:
            continue
        if _YEAR_RE.search(lowered) or "month" in _TEXT_INDEX.scan(lowered):
            count += 1
    return count


def _has_period_bookend(raw_stubs) -> bool:
    """Stub rows that bookend a period, balance-named or not."""
    for stub in raw_stubs:
        found = _TEXT_INDEX.scan((stub or "").lower())
        if "period" in found:
            return True
        if "balance" in found and ("beginning" in found or "end_of" in found):
            return True
    return False


def _carries_period_date(texts) -> bool:
    """A year token anywhere across the texts."""
    joined = " ".join((text or "").lower() for text in texts)
    return bool(_YEAR_RE.search(joined))


def _carries_component_keys(stub_keys, header_keys_, spec) -> bool:
    """A non-OCI equity component term on the surface: a
    component stub key, or a component header token."""
    stub_scan, header_scan = _key_scans(spec, stub_keys, header_keys_)
    return "component_key" in stub_scan or "component_header" in header_scan


def _credited_dated_balance_count(raw_stubs, dated_texts) -> int:
    """The stock count, credited to 1 when the statement phrases
    its bookends without dates and carries the period date on
    its header or caption surface instead."""
    count = _dated_balance_count(raw_stubs)
    if count:
        return count
    if _has_period_bookend(raw_stubs) and _carries_period_date(dated_texts):
        return 1
    return 0


class EquitySeparatorText:
    """The packet text surface the equity cascade reads."""

    def __init__(self, table_text, caption_stack=()):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [tuple(c.strip() for c in ln.split("|")) for ln in lines]
        self.raw_stubs = tuple(row[0] for row in self.rows)
        self.stubs = tuple(stub for stub in self.raw_stubs if stub)
        self.headers = tuple(cell for row in self.rows[:_HEADER_LINES] for cell in row)
        self.caption_stack = list(caption_stack or [])
        self.stub_keys = frozenset(
            key for key in (stub_key(stub) for stub in self.stubs) if key
        )
        self.header_keys = header_keys(self.headers)
        self.dated_balance_rows = _credited_dated_balance_count(
            self.raw_stubs,
            list(self.headers) + list(self.caption_stack) + list(self.raw_stubs),
        )
        years = set()
        for cell in self.headers:
            years.update(_YEAR_RE.findall(cell))
        self.header_years = frozenset(years)

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class EquitySeparatorVerdict:
    """The cascade's read: admitted unless a priced leg fires."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def evaluate_equity_separator(
    text: EquitySeparatorText, spec: EquitySeparatorSpec, *, walk_closed: bool = False
) -> EquitySeparatorVerdict:
    """Fire the claim-local legs in their priced order."""
    if not text.rows:
        return EquitySeparatorVerdict(False, False, (), "no grid rows")
    legs = []
    if len(text.rows) <= spec.max_rows:
        legs.append(f"rows_le_{spec.max_rows}")
    if len(text.header_years) >= spec.span_years_min and not walk_closed:
        legs.append(f"span_ge_{spec.span_years_min}")
    if text.dated_balance_rows == 0:
        legs.append("core_gate")
    stub_scan, header_scan = _key_scans(spec, text.stub_keys, text.header_keys)
    if "component_key" not in stub_scan and "component_header" not in header_scan:
        legs.append("component_gate")
    for key in spec.stub_keys:
        if key in stub_scan.get("stub_key", ()):
            legs.append(f"stub:{key}")
    for token in spec.header_tokens:
        if token in header_scan.get("header_token", ()):
            legs.append(f"hdr:{token}")
    fired = bool(legs)
    detail = (
        "equity separator fired: " + ", ".join(legs)
        if fired
        else "equity separator clear"
    )
    return EquitySeparatorVerdict(fired, True, tuple(legs), detail)


@dataclass(frozen=True, slots=True)
class EquityCandidateFeatures:
    """One candidate's assignment-pass features and score tuple."""

    dated_balance_rows: int
    supporting_points: int
    row_count: int

    @property
    def score(self) -> tuple[int, int, int]:
        """Core carriage first, then supporting points, then size."""
        return (
            1 if self.dated_balance_rows >= 1 else 0,
            self.supporting_points,
            self.row_count,
        )


def _candidate_features(dated_balance_rows, stub_keys, header_keys, row_count, spec):
    """Supporting points count only toward core-satisfying rank."""
    if dated_balance_rows >= 2:
        supporting = 2
    elif dated_balance_rows == 1:
        supporting = 1
    else:
        supporting = 0
    stub_scan, header_scan = _key_scans(spec, stub_keys, header_keys)
    flow = bool(stub_scan.get("flow_key")) or "flow_prefix" in stub_scan
    if flow:
        supporting += 1
    if "total_key" in header_scan:
        supporting += 1
    supporting += len(stub_scan.get("core_vocab", ()))
    return EquityCandidateFeatures(dated_balance_rows, supporting, row_count)


def equity_candidate_features(
    text: EquitySeparatorText, spec: EquitySeparatorSpec
) -> EquityCandidateFeatures:
    """Assignment features over the packet text surface."""
    return _candidate_features(
        text.dated_balance_rows,
        text.stub_keys,
        text.header_keys,
        len(text.rows),
        spec,
    )


def equity_candidate_features_from_geometry(geometry, spec) -> EquityCandidateFeatures:
    """Assignment features over a claimed geometry's stamped text."""
    stub_keys = frozenset(
        key for key in (stub_key(stub) for stub in geometry.stubs) if key
    )
    return _candidate_features(
        _credited_dated_balance_count(
            geometry.stubs, list(geometry.headers) + list(geometry.stubs)
        ),
        stub_keys,
        header_keys(geometry.headers),
        geometry.grid_rows,
        spec,
    )


def apply_equity_assignment(geometries, results):
    """Filing-level pass: a strictly dominated equity candidate
    is eliminated; runs before the primary gate's final pass.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "equity_statement"
    spec = EQUITY_SEPARATOR_SPECS[family]
    claimed = [i for i, result in enumerate(results) if family in result.claims]
    if not claimed:
        return list(results)
    features = {
        i: equity_candidate_features_from_geometry(geometries[i], spec) for i in claimed
    }
    refused: dict[int, str] = {}
    if len(claimed) >= 2:
        for i in claimed:
            dominated = any(
                features[j].score > features[i].score for j in claimed if j != i
            )
            if dominated:
                refused[i] = "equity assignment: strictly dominated candidate"
    if not refused:
        return list(results)
    out = []
    for i, result in enumerate(results):
        if i not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(family)
        if score is not None:
            scores[family] = FamilyScore(
                score.family,
                score.total,
                score.by_channel,
                score.evidence + (ClaimEvidence("gate", refused[i], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(name for name in result.claims if name != family),
                contested=tuple(name for name in result.contested if name != family),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out


# ---------------------------------------------------------------
# Production wiring: the stage adapter reads the assembled
# table's full grid (context rows) through the same derivation.


def evaluate_form_test_equity_separator(table, spec) -> EquitySeparatorVerdict:
    """Stage entry: evaluate the cascade over an assembled table."""
    context = table.context
    text = EquitySeparatorText.from_rows(
        context.rows, list(context.caption_stack) + list(table.caption.titles)
    )
    walk_closed = (
        _column_walk(table, SEAT_TEST_SPECS_BY_FAMILY["equity_statement"]) >= 1
    )
    return evaluate_equity_separator(
        text, EQUITY_SEPARATOR_SPECS[spec.family], walk_closed=walk_closed
    )
