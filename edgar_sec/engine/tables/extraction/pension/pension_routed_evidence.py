"""Pension routed separator evidence (TEST_PENSION_ROUTED).

The routed separator over one table: marker sub-kind
determination, the routed kind's priced cell, the host
increment, the segment leg; undetermined specimens abstain.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from edgar_sec.foundation.text.dates import STRICT_YEAR_TOKEN_PATTERN
from edgar_sec.foundation.text.patterns import RE_NON_ALNUM, RE_WHITESPACE
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    ASSETS_CORE_SHARE,
    ASSETS_CORE_TERMS,
    BENEFIT_HDR_TERMS,
    CELL_LEGS,
    DROP_TOKS,
    HEADER_STOP_TOKENS,
    HOST_SUPP_VOCAB,
    KIND_ORDER,
    MARKER_STEMS,
    MONTH_TOKENS,
    MOVE_WORDS,
    PENSION_ROUTED_SPEC,
    STRONG_STEMS,
    PensionRoutedSpec,
)

_DIGITS_RE = re.compile(r"\b\d+\b")
_BOOKEND_BEGIN_RE = re.compile(r"beginning|opening balance|balance at (the )?beginning")
_YEAR_TOKEN_RE = re.compile(rf"^(?:{STRICT_YEAR_TOKEN_PATTERN})$")
_HEADER_LINES = 3


def norm(text):
    """The priced normalization, composed from the foundation homes."""
    lowered = RE_NON_ALNUM.sub(" ", (text or "").lower())
    return RE_WHITESPACE.sub(" ", lowered).strip()


def stub_key(stub):
    """The priced stub key: digits and months dropped, first 8 tokens."""
    keyed = _DIGITS_RE.sub(" ", norm(stub))
    toks = [t for t in keyed.split() if t not in MONTH_TOKENS and len(t) > 1]
    return " ".join(toks[:8])


def header_keys(header_cells: tuple[str, ...]) -> frozenset:
    """Header keys: whole-cell stub keys plus content tokens."""
    keys = set()
    for cell in header_cells:
        keyed = stub_key(cell)
        if len(keyed) >= 3:
            keys.add(keyed)
        for token in norm(cell).split():
            if (
                len(token) > 2
                and not token.isdigit()
                and token not in HEADER_STOP_TOKENS
            ):
                keys.add(token)
    return frozenset(keys)


class PensionRoutedText:
    """The packet text surface the routed separator reads."""

    def __init__(self, table_text, caption_stack=()):
        self.table_text = table_text or ""
        self.caption_stack = list(caption_stack or [])

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class PensionRoutedVerdict:
    """The separator's read: admitted unless a priced leg kills."""

    admitted: bool
    detail: str


@dataclass(frozen=True, slots=True)
class _Read:
    features: frozenset
    stub_keys: tuple
    blobs: dict
    all_keys: frozenset
    payments_hits: frozenset
    stub_year_ladder: bool
    benefit_terms: tuple
    max_raw_mult: int


def _read(text: PensionRoutedText) -> _Read:
    lines = [ln for ln in text.table_text.split("\n") if ln.strip()]
    rows = [[c.strip() for c in ln.split("|")] for ln in lines]
    stubs = [r[0] for r in rows if r and r[0]]
    headers = [c for r in rows[:_HEADER_LINES] for c in r if c]
    colcells = [c for r in rows[:_HEADER_LINES] for c in r[1:] if c]
    stub_keys = tuple(k for k in (stub_key(s) for s in stubs) if len(k) >= 3)
    features = {f"stub:{k}" for k in stub_keys}
    hkeys = header_keys(tuple(headers))
    features |= {f"hdr:{k}" for k in hkeys}
    if len(lines) <= 3:
        features.add("rows_le_3")
    if len(lines) <= 5:
        features.add("rows_le_5")
    stub_blob = " ".join(norm(s) for s in stubs)
    if _BOOKEND_BEGIN_RE.search(stub_blob):
        features.add("bookend_begin")
    move_hits = sum(1 for s in stubs if MOVE_WORDS & set(norm(s).split()))
    if round(move_hits / max(1, len(stubs)), 3) <= 0.25:
        features.add("movedens_le_0.25")
    blobs = {
        "stubfull": stub_blob,
        "hdr": " ".join(norm(h) for h in headers),
        "cap": " ".join(norm(c) for c in text.caption_stack),
        "col": " ".join(norm(c) for c in colcells),
    }
    keysets = {
        "stub": set(stub_keys),
        "hdr": {k for k in (stub_key(h) for h in headers) if len(k) >= 3},
        "cap": {k for k in (stub_key(c) for c in text.caption_stack) if len(k) >= 3},
        "col": {k for k in (stub_key(c) for c in colcells) if len(k) >= 3},
    }
    payments_hits = frozenset(
        stem
        for stem in MARKER_STEMS["payments"]
        if any(stem in blob for blob in blobs.values())
    )
    year_stubs = 0
    for stub in stubs:
        toks = [t for t in norm(stub).replace("-", " ").split() if t not in DROP_TOKS]
        if toks and all(_YEAR_TOKEN_RE.match(t) for t in toks):
            year_stubs += 1
    benefit_terms = tuple(
        term
        for term in BENEFIT_HDR_TERMS
        if term in blobs["hdr"] or term in blobs["cap"] or term in blobs["col"]
    )
    raw = Counter(t for t in (norm(s) for s in stubs) if t)
    return _Read(
        features=frozenset(features),
        stub_keys=stub_keys,
        blobs=blobs,
        all_keys=frozenset().union(*keysets.values()),
        payments_hits=payments_hits,
        stub_year_ladder=year_stubs >= 4,
        benefit_terms=benefit_terms,
        max_raw_mult=max(raw.values()) if raw else 0,
    )


def _route(stub_keys) -> str | None:
    scores = {}
    hits = {}
    for kind in KIND_ORDER:
        found = sorted(
            {s for s in MARKER_STEMS[kind] if any(s in k for k in stub_keys)}
        )
        hits[kind] = found
        scores[kind] = len(found)
    member = [
        k
        for k in KIND_ORDER
        if scores[k] >= 2 or (scores[k] == 1 and hits[k][0] in STRONG_STEMS)
    ]
    if not member:
        return None
    return min(member, key=lambda k: (-scores[k], KIND_ORDER.index(k)))


def _cell_kill(kind, features) -> tuple[bool, str]:
    if kind == "assets":
        present = sum(1 for t in ASSETS_CORE_TERMS if f"stub:{t}" in features)
        killed = present < ASSETS_CORE_SHARE * len(ASSETS_CORE_TERMS)
        return killed, "core_share<0.5 of strong"
    for leg in CELL_LEGS[kind]:
        if leg.startswith("A:") and leg[2:] in features:
            return True, leg
        if leg.startswith("B:") and leg[2:] not in features:
            return True, leg
    return False, ""


def _payments_cell_kill(read: _Read) -> bool:
    return (
        not read.payments_hits and not read.stub_year_ladder and not read.benefit_terms
    )


def _best_host(all_keys, min_hits) -> str | None:
    best = None
    best_count = 0
    for family in sorted(HOST_SUPP_VOCAB):
        count = len(HOST_SUPP_VOCAB[family] & all_keys)
        if count >= min_hits and (best is None or count > best_count):
            best = family
            best_count = count
    return best


def evaluate_pension_routed(
    text: PensionRoutedText, spec: PensionRoutedSpec = PENSION_ROUTED_SPEC
) -> PensionRoutedVerdict:
    """Evaluate the routed separator over one table's text."""
    read = _read(text)
    kind = _route(read.stub_keys)
    if kind is not None:
        if kind == "payments":
            killed = _payments_cell_kill(read)
            state = "fired" if killed else "clear"
            return PensionRoutedVerdict(
                not killed, f"kind:payments allsurf_xboth {state}"
            )
        killed, leg = _cell_kill(kind, read.features)
        detail = f"kind:{kind} cell fired ({leg})" if killed else f"kind:{kind} clear"
        return PensionRoutedVerdict(not killed, detail)
    if spec.payments_due_term in read.blobs["cap"] or (
        spec.payments_due_term in read.blobs["hdr"]
    ):
        return PensionRoutedVerdict(
            False, f"inc:cap_payments_due (host {spec.payments_due_host})"
        )
    host = _best_host(read.all_keys, spec.host_min_hits)
    if host is not None:
        return PensionRoutedVerdict(False, f"inc:host2_supp (host {host})")
    if spec.item201d_phrase in read.blobs["hdr"] or (
        spec.item201d_phrase in read.blobs["col"]
    ):
        return PensionRoutedVerdict(
            False, f"inc:hdr_item201d (host {spec.item201d_host})"
        )
    if read.max_raw_mult >= spec.seg_min_multiplicity:
        return PensionRoutedVerdict(False, "seg:seg_raw3")
    if read.benefit_terms:
        rule = "benefit_payments" if read.stub_year_ladder else "benefit_hdr"
        killed = _payments_cell_kill(read)
        state = "fired" if killed else "clear"
        return PensionRoutedVerdict(not killed, f"ext:{rule} allsurf_xboth {state}")
    return PensionRoutedVerdict(True, "abstain")


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_pension_routed(table, spec):
    """Stage adapter: evaluate the routed separator over a table."""
    text = PensionRoutedText.from_rows(table.context.rows, table.context.caption_stack)
    return evaluate_pension_routed(text)


def failing_pension_routed_outcome(form_tests, family, kind):
    """The stamped routed outcome failing one family's gate.

    Delegates to the homed outcome reader in core_form_evidence."""
    return failing_core_form_outcome(form_tests, family, kind)
