"""Tests for mining fact concept token n-grams and taxonomy coverage."""

import pyarrow.parquet as pq

import pyarrow as pa

from edgar_sec.engine.xbrl.discovery.fixture_miner import (
    BundleFacts,
    build_modelledness_report,
    evaluate_taxonomy_fact_coverage,
    mine_fact_token_ngrams,
)
from edgar_sec.engine.xbrl.discovery.placement_slices import tokenize_fact_concept
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup
from tests.support import fixture_path


def test_tokenize_fact_concept() -> None:
    """Verify camel-case and extension fact concept tokenization."""
    qname = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    tokens = tokenize_fact_concept(qname)
    assert tokens == [
        "revenue",
        "from",
        "contract",
        "with",
        "customer",
        "excluding",
        "assessed",
        "tax",
    ]

    ext_qname = "jpm:PreProvisionProfit"
    assert tokenize_fact_concept(ext_qname) == ["pre", "provision", "profit"]


def test_mine_fact_token_ngrams() -> None:
    """Verify fact concept n-gram extraction across real grounded filing."""
    facts_p = fixture_path("xbrl/seed/msft_2024_10k/facts.parquet")
    table = pq.read_table(facts_p)

    ngrams = mine_fact_token_ngrams(table, n_range=(2, 3))
    assert len(ngrams) > 50
    assert ("contract", "customer") in ngrams or ("operating", "lease") in ngrams


def test_evaluate_taxonomy_fact_coverage() -> None:
    """Verify fact taxonomy coverage metrics and isolation of OOV n-grams."""
    facts_p = fixture_path("xbrl/seed/msft_2024_10k/facts.parquet")
    table = pq.read_table(facts_p)

    report = evaluate_taxonomy_fact_coverage(table)
    assert report.total_facts > 1000
    assert report.unique_concepts > 100
    assert 0.0 < report.token_coverage_ratio <= 1.0
    assert len(report.top_oov_ngrams) > 0


def _facts_table(qnames: list[str]) -> pa.Table:
    """Build a minimal facts table carrying only concept QNames."""
    return pa.table({"concept_qname": qnames})


def test_build_modelledness_report_buckets_and_ranking() -> None:
    """Verify bucket rules, collision sizes, and candidate ranking."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    shared = [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:Revenues",
        "us-gaap:SomeDisclosureTableTextBlock",
        "acme:CustomThing",
    ]
    bundles = [
        BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(shared)),
        BundleFacts(firm="BBB", sic_code="2000", facts=_facts_table(shared)),
    ]

    report = build_modelledness_report(bundles, lexicon)

    assert report.total_concepts == 4
    assert report.total_fact_rows == 8
    by_qname = {r.qname: r for r in report.concepts}
    cash = by_qname["us-gaap:CashAndCashEquivalentsAtCarryingValue"]
    assert cash.bucket == "candidate"
    assert cash.token_count >= 5
    assert len(cash.modifiers) <= 1
    assert cash.firm_count == 2
    assert cash.sic_count == 2
    assert by_qname["us-gaap:Revenues"].bucket == "modelled"
    assert by_qname["us-gaap:SomeDisclosureTableTextBlock"].bucket == "textblock"
    assert by_qname["acme:CustomThing"].bucket == "extension"
    assert dict(report.bucket_counts) == {
        "candidate": 1,
        "extension": 1,
        "modelled": 1,
        "textblock": 1,
    }
    assert [r.qname for r in report.candidates] == [cash.qname]
    assert report.long_and_bare_us_gaap == 1


def test_report_records_derived_and_presumed_coordinates() -> None:
    """Derived and presumed coordinates are reported beside faithful atoms."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    defaults = load_domain_taxonomy().default_coordinates
    qnames = [
        "acme:AccountsPayable",
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:LongTermDebtMaturitiesDueInFiveYears",
    ]
    bundles = [BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(qnames))]

    report = build_modelledness_report(bundles, lexicon, defaults=defaults)

    by_qname = {r.qname: r for r in report.concepts}
    bare = by_qname["acme:AccountsPayable"]
    assert bare.presumed_modifier == "M_CURRENT"
    assert "M_CURRENT" not in bare.modifiers
    assert by_qname["us-gaap:AccountsPayableCurrent"].presumed_modifier == ""
    due = by_qname["us-gaap:LongTermDebtMaturitiesDueInFiveYears"]
    assert due.derived_horizon == "M_NONCURRENT"


def test_report_mines_residual_collocations() -> None:
    """Recurrent residual phrases surface as merge candidates with spread."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    shared = [
        "acme:WizzleFrotzAlpha",
        "acme:WizzleFrotzBeta",
        "acme:WizzleFrotzGamma",
        "acme:AlphaSummaryTableTextBlock",
        "acme:BetaSummaryTableTextBlock",
        "acme:GammaSummaryTableTextBlock",
    ]
    bundles = [
        BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(shared)),
        BundleFacts(firm="BBB", sic_code="2000", facts=_facts_table(shared)),
    ]

    report = build_modelledness_report(bundles, lexicon)

    by_phrase = {c.phrase: c for c in report.residual_collocations}
    wizzle = by_phrase[("wizzle", "frotz")]
    assert wizzle.frequency == 3
    assert wizzle.firm_count == 2
    assert wizzle.sic_count == 2
    assert wizzle.structural is False
    assert wizzle.example_qname.startswith("acme:")
    assert by_phrase[("text", "block")].structural is True


def test_report_rebases_residuals_into_noise_and_intent() -> None:
    """Stopword/digit-only residuals split from intent-bearing ones."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    shared = [
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
        "us-gaap:DerivativeForwardExchangeRate1",
        "acme:CustomThing",
    ]
    bundles = [
        BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(shared)),
        BundleFacts(firm="BBB", sic_code="2000", facts=_facts_table(shared)),
    ]

    report = build_modelledness_report(bundles, lexicon)

    classes = {r.qname: r.residual_class for r in report.concepts}
    assert classes["us-gaap:CashCashEquivalentsAndShortTermInvestments"] == "noise_only"
    assert classes["us-gaap:DerivativeForwardExchangeRate1"] == "noise_only"
    assert classes["acme:CustomThing"] == "intent_bearing"
    assert report.us_gaap_unknown_noise_only == 1
    assert report.residual_noise_token_total >= 2
    assert report.residual_intent_token_total >= 2


def test_report_flags_frame_conflicts_from_period_profiles() -> None:
    """Duration facts under a balance-sheet head surface as a frame conflict."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    cash = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    facts = pa.table(
        {
            "concept_qname": ["us-gaap:Assets"] * 6 + [cash] * 6,
            "period_type": ["duration"] * 6 + ["instant"] * 6,
        }
    )
    arcs = pa.table(
        {
            "parent_qname": ["us-gaap:StatementOfFinancialPositionAbstract"] * 2,
            "child_qname": ["us-gaap:Assets", cash],
        }
    )
    bundles = [
        BundleFacts(firm="AAA", sic_code="1000", facts=facts, presentation_arcs=arcs)
    ]

    report = build_modelledness_report(bundles, lexicon)

    assert len(report.frame_conflicts) == 1
    conflict = report.frame_conflicts[0]
    assert conflict.qname == "us-gaap:Assets"
    assert conflict.head_slice == "BalanceSheet"
    assert conflict.period_profile == "duration"
    assert conflict.duration_facts == 6
    assert conflict.placement_slices == ("BalanceSheet",)


def test_report_excludes_unmodelled_dei_cover_facts() -> None:
    """Unmodelled dei cover facts are a declared exclusion, not a gap."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    shared = ["dei:DocumentType", "dei:EntityCommonStockSharesOutstanding"]
    bundles = [
        BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(shared)),
        BundleFacts(firm="BBB", sic_code="2000", facts=_facts_table(shared)),
    ]

    report = build_modelledness_report(bundles, lexicon)

    buckets = {r.qname: r.bucket for r in report.concepts}
    assert buckets["dei:DocumentType"] == "excluded"
    assert buckets["dei:EntityCommonStockSharesOutstanding"] == "extension"
    assert dict(report.bucket_counts)["excluded"] == 1


def test_report_buckets_all_text_concepts_as_textblock() -> None:
    """A concept with only text-valued facts is a text disclosure."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    facts = pa.table(
        {
            "concept_qname": ["us-gaap:UseOfEstimates", "us-gaap:Assets"],
            "numeric_value": [None, 10.0],
        }
    )
    bundles = [BundleFacts(firm="AAA", sic_code="1000", facts=facts)]

    report = build_modelledness_report(bundles, lexicon)

    buckets = {r.qname: r.bucket for r in report.concepts}
    assert buckets["us-gaap:UseOfEstimates"] == "textblock"
    assert buckets["us-gaap:Assets"] != "textblock"


def test_adequacy_identity_missing_for_structural_only_atom() -> None:
    """A head plus M_CURRENT alone carries no identity; a receivable atom does."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    qnames = ["us-gaap:OtherLiabilitiesCurrent", "us-gaap:AccountsReceivableNetCurrent"]
    bundles = [BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(qnames))]

    report = build_modelledness_report(bundles, lexicon)

    records = {r.qname: r for r in report.concepts}
    other = records["us-gaap:OtherLiabilitiesCurrent"]
    assert other.has_identity is False
    assert other.adequacy == "identity_missing"
    assert other.explained_share < 1.0
    receivable = records["us-gaap:AccountsReceivableNetCurrent"]
    assert receivable.has_identity is True
    assert receivable.adequacy == "proper"
    assert dict(report.adequacy_counts)["identity_missing"] == 1


def test_identity_collisions_list_shared_atom_members() -> None:
    """An atom shared by five distinct concepts surfaces with member residuals."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    qnames = [
        "us-gaap:OtherLiabilitiesCurrent",
        "us-gaap:OtherSundryLiabilitiesCurrent",
        "tsla:AccruedAndOtherCurrentLiabilities",
        "tsla:AccruedWarrantyReserveCurrentPortion",
        "us-gaap:LiabilitiesCurrent",
    ]
    bundles = [BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(qnames))]

    report = build_modelledness_report(bundles, lexicon)

    assert len(report.identity_collisions) == 1
    collision = report.identity_collisions[0]
    assert collision.concept_count == 5
    members = dict(collision.members)
    assert members["us-gaap:OtherLiabilitiesCurrent"] == ("Other",)
    assert members["us-gaap:LiabilitiesCurrent"] == ()


def test_pattern_groups_merge_namespaces_by_signature() -> None:
    """The same decomposed signature in two firms' namespaces forms one group."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    bundles = [
        BundleFacts(
            firm="AAA",
            sic_code="1000",
            facts=_facts_table(["acme:LeaseLiabilityCurrent"]),
        ),
        BundleFacts(
            firm="BBB",
            sic_code="2000",
            facts=_facts_table(["beta:LeaseLiabilityCurrent"]),
        ),
    ]

    report = build_modelledness_report(bundles, lexicon)

    (group,) = report.pattern_groups
    assert group.head == "H_LIABILITY"
    assert group.modifiers == ("M_CURRENT", "M_LEASE_ROU")
    assert group.residual_signature == ()
    assert group.firms == ("AAA", "BBB")
    assert group.sics == ("1000", "2000")
    assert group.concept_count == 2


def test_report_records_temporal_relations_and_cardinality() -> None:
    """Temporal/relations ride the record; exclusive duals warn, textblocks exempt."""
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    qnames = [
        "us-gaap:LongTermDebtMaturitiesDueInFiveYears",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:ScheduleOfEarningsPerShareBasicAndDilutedTableTextBlock",
    ]
    bundles = [BundleFacts(firm="AAA", sic_code="1000", facts=_facts_table(qnames))]

    report = build_modelledness_report(
        bundles, taxonomy.token_lexicon, sibling_groups=taxonomy.sibling_groups
    )
    by_qname = {r.qname: r for r in report.concepts}
    assert by_qname[qnames[0]].temporal == "48-60:BUCKET"
    assert by_qname[qnames[1]].relations == ("EXCLUDING",)
    # The EPS combined-presentation textblock is exempt; nothing else duals.
    assert report.cardinality_violations == ()

    synthetic = (
        SiblingGroup(
            group="SYNTHETIC", members=("M_PRETAX", "M_TAX"), cardinality="exclusive"
        ),
    )
    flagged = build_modelledness_report(
        bundles, taxonomy.token_lexicon, sibling_groups=synthetic
    )
    assert [(g, a) for g, a, _ in flagged.cardinality_violations] == [
        ("SYNTHETIC", str(by_qname[qnames[1]].atom))
    ]


def test_modelledness_buckets_follow_declared_type() -> None:
    """Declared type, not the name, decides the textblock bucket."""
    from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
    from edgar_sec.engine.xbrl.storage.storage import declarations_to_arrow_table
    from edgar_sec.engine.xbrl.taxonomy.item_types import TextCoordinateRule

    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    qnames = [
        "us-gaap:SomeDisclosureTableTextBlock",
        "us-gaap:SomeNarrativeDisclosure",
        "us-gaap:UnresolvedThingTextBlock",
    ]
    declarations = declarations_to_arrow_table(
        (
            ConceptDeclaration(
                concept_qname=qnames[0],
                name="SomeDisclosureTableTextBlock",
                item_type="xbrli:monetaryItemType",
            ),
            ConceptDeclaration(
                concept_qname=qnames[1],
                name="SomeNarrativeDisclosure",
                item_type="xbrli:stringItemType",
            ),
        )
    )
    bundle = BundleFacts(
        firm="AAA",
        sic_code="1000",
        facts=_facts_table(qnames),
        declarations=declarations,
    )
    rule = TextCoordinateRule(
        modifier_id="M_TEXT_NODE",
        item_types=frozenset({"textBlockItemType", "stringItemType"}),
    )
    typed = build_modelledness_report([bundle], lexicon, text_rule=rule)
    buckets = {record.qname: record.bucket for record in typed.concepts}
    assert buckets[qnames[0]] != "textblock"
    assert buckets[qnames[1]] == "textblock"
    assert buckets[qnames[2]] == "textblock"
    untyped = build_modelledness_report([bundle], lexicon)
    untyped_buckets = {record.qname: record.bucket for record in untyped.concepts}
    assert untyped_buckets[qnames[0]] == "textblock"
    assert untyped_buckets[qnames[1]] != "textblock"
