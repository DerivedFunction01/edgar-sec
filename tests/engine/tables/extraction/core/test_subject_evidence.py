"""Contract tests for the subject-evidence map data and loader."""

from edgar_sec.engine.tables.extraction.core.subjects.subject_evidence import (
    CHANNELS,
    CLOSURE_POLICY,
    MAP_VERSION,
    load_map,
)

BANNED_TOKENS = ("xbrl", "us-gaap", "usgaap", "taxonomy", "concept tag", "dei ")


def test_map_loads_with_version_and_closure_policy():
    m = load_map()
    assert m.version == MAP_VERSION
    assert m.closure_policy == CLOSURE_POLICY == "corroboration_only_never_negative"


def test_every_family_carries_terms_on_the_load_bearing_channels():
    m = load_map()
    assert len(m.families) == 21
    absent = {a.family for a in m.priced_absences}
    for family in m.families:
        if family in absent:
            assert not m.terms_for(family), family
            continue
        assert m.terms_for(family), family
        if m.labelled_members[family] >= 30:
            channels = {t.channel for t in m.terms_for(family)}
            assert "leadin" in channels, family
            # debt_maturity's stubs are dates and instrument names:
            # its stub-side evidence is the shared ladder terms.
            assert "stub" in channels or family == "debt_maturity", family
    assert absent == {"commitments_contingencies"}


def test_terms_are_measured_flat_and_normalized():
    m = load_map()
    seen = set()
    for t in m.terms:
        assert t.channel in CHANNELS
        assert t.support >= 2
        assert t.support == t.support_b + t.support_d
        assert 0.0 < t.share <= 1.0
        assert 0.34 <= t.confidence <= 1.0
        if m.labelled_members[t.family] >= 12:
            assert t.confidence >= 0.5
        assert t.term == t.term.lower() and t.term == t.term.strip()
        key = (t.family, t.channel, t.term)
        assert key not in seen
        seen.add(key)


def test_no_taxonomy_signal_or_closure_channel_anywhere():
    m = load_map()
    for t in m.terms:
        assert t.channel != "closure"
        low = t.term.lower()
        assert not any(b in low for b in BANNED_TOKENS), t.term
    assert {c.channel for c in m.channels} == set(CHANNELS)


def test_channel_weights_carry_step0_pricing():
    m = load_map()
    leadin = m.channel_weight("leadin")
    stub = m.channel_weight("stub")
    caption = m.channel_weight("caption")
    assert leadin is not None and stub is not None and caption is not None
    assert leadin > 0.7 and stub > 0.7
    by_channel = {c.channel: c for c in m.channels}
    assert by_channel["caption"].presence_b < 0.5
    assert by_channel["leadin"].presence_b > 0.8


def test_named_containment_edges_are_measured():
    m = load_map()
    edges = {(e.family, e.other_family): e for e in m.containment_edges}
    aoci = edges[("equity_statement", "aoci_rollforward")]
    assert aoci.kind == "contains_column" and aoci.support >= 4
    ladder = edges[("debt_maturity", "lease_maturity")]
    assert ladder.kind == "shared_evidence" and ladder.support >= 3
    assert ladder.basis == "shared_stub_term_min_support_sum"
    assert ("lease_maturity", "debt_maturity") in edges
    assert m.edge_terms, "ladder shared stub terms are measured"
    for et in m.edge_terms:
        assert et.edge == "debt_maturity/lease_maturity"
        assert et.support_debt >= 3 and et.support_lease >= 3
    combined = edges[("comprehensive_income", "income_statement")]
    assert combined.kind == "combined_presentation"


def test_equity_inheritance_is_priced_first_class():
    m = load_map()
    rows = {r.family: r for r in m.inheritance}
    equity = rows["equity_statement"]
    assert equity.members > 100
    assert equity.title_decides_support >= 10
    assert equity.title_decides_share > 0.1
