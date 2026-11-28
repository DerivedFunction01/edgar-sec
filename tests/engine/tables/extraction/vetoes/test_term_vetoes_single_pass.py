"""Single-pass term vetoes: the unified-index conversion pins.

Substring semantics (intra-word hits included), spec-order
first-hit identity, and equivalence with the per-term scan.
"""

from __future__ import annotations

import random

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    TERM_VETOES,
    term_veto_hits,
    term_veto_hits_by_channel,
)


def _reference(geometry: GeometryText) -> dict:
    """The pre-conversion per-term substring scan, as priced."""
    texts = {
        "lead": normalize_text(geometry.lead),
        "body": normalize_text(geometry.grid_text),
    }
    hits: dict = {}
    for spec in TERM_VETOES:
        text = texts[spec.channel]
        if not text:
            continue
        for term in spec.terms:
            if normalize_text(term) in text:
                tiers = hits.setdefault(spec.family, {})
                by_channel = tiers.setdefault(spec.tier, {})
                if spec.channel not in by_channel:
                    by_channel[spec.channel] = term
                break
    return hits


def test_intra_word_substring_hit_is_preserved() -> None:
    # "lease" is priced as a literal substring: it hits inside
    # "release", which a word-boundary matcher would miss.
    geometry = GeometryText(lead="The release schedule follows.")
    hits = term_veto_hits_by_channel(geometry)
    assert hits["debt_maturity"]["scored"] == {"lead": "lease"}


def test_first_hit_is_spec_order_not_text_position() -> None:
    geometry = GeometryText(lead="Acquisition and maturity dates.")
    assert term_veto_hits(geometry)["debt_maturity"]["scored"] == "maturity"


def test_channels_do_not_cross() -> None:
    # "senior notes" is the family's body hard term; the same
    # words on the lead channel land on the lead scored list.
    lead_only = GeometryText(lead="Senior notes offering.")
    hits = term_veto_hits_by_channel(lead_only)
    assert hits["debt_maturity"]["scored"] == {"lead": "senior notes"}
    assert "hard" not in hits["debt_maturity"]
    body_only = GeometryText(grid_text="Senior notes due 2030.")
    hits = term_veto_hits_by_channel(body_only)
    assert hits["debt_maturity"]["hard"] == {"body": "senior notes"}


def test_empty_texts_hit_nothing() -> None:
    assert term_veto_hits_by_channel(GeometryText()) == {}


def test_equivalence_battery_against_the_per_term_scan() -> None:
    rng = random.Random(20261127)
    terms = [term for spec in TERM_VETOES for term in spec.terms]
    fillers = ("the", "of", "and", "schedule", "follows", "x", "2030")
    texts = []
    for _ in range(300):
        words = []
        for _ in range(rng.randrange(0, 14)):
            pick = rng.random()
            if pick < 0.45:
                words.append(rng.choice(terms))
            elif pick < 0.6:
                # Embed a term inside a larger word: substring
                # semantics must still hit, boundary must not.
                words.append("pre" + rng.choice(terms).replace(" ", "") + "post")
            else:
                words.append(rng.choice(fillers))
        texts.append(" ".join(words))
    for text in texts:
        for geometry in (
            GeometryText(lead=text),
            GeometryText(grid_text=text),
            GeometryText(lead=text, grid_text=text),
        ):
            assert term_veto_hits_by_channel(geometry) == _reference(geometry)
