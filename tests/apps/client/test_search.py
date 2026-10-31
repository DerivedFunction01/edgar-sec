"""Close-match fact search: terms resolve to atoms, hits rank by the ladder."""

from edgar_sec.apps.client.facts import build_display_records
from edgar_sec.apps.client.search import resolve_search_targets, search_facts
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import NEAR
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_facts

_FOLDER = "msft_2024_10k"
_REVENUE_QNAME = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_RECOGNIZED_QNAME = (
    "msft:ContractWithCustomerLiabilityRevenueRecognizedIncludingAdditions"
)


def _pool():
    taxonomy = load_domain_taxonomy()
    facts = load_seed_facts(_FOLDER)
    return facts, build_display_records(facts, taxonomy), taxonomy


def test_resolve_alias_term_uses_declared_targets() -> None:
    """An alias term resolves to its declared atom-coordinate targets."""
    taxonomy = load_domain_taxonomy()
    targets, residuals = resolve_search_targets("cfo", taxonomy)
    assert targets == taxonomy.query_alias_atoms("cfo")
    assert residuals == ()


def test_search_revenue_ranks_filed_concepts_by_the_ladder() -> None:
    """Bare revenue ranks the filed total NEAR by subsumption, diff shown."""
    facts, records, taxonomy = _pool()
    result = search_facts("revenue", facts, records, taxonomy)
    assert result.partial is False
    assert result.target_atom == Atom("H_REVENUE")
    by_qname = {hit.qname: hit for hit in result.hits}
    filed = by_qname[_REVENUE_QNAME]
    assert filed.tier == NEAR
    assert filed.rule == "subsumption"
    assert filed.modifier_distance == 3
    assert filed.target_only == ()
    assert filed.hit_only == ("M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX")
    assert filed.facts
    recognized = by_qname[_RECOGNIZED_QNAME]
    assert recognized.tier == NEAR
    assert recognized.rule == "single_modifier_difference"
    assert recognized.modifier_distance == 1
    assert recognized.hit_only == ("M_CONTRACT_CUSTOMER",)
    assert recognized.residual_mass == (1, 2)


def test_search_partial_term_marks_partial_and_still_ranks() -> None:
    """A term with an unclaimed token ranks its claimed atom, marked partial."""
    facts, records, taxonomy = _pool()
    result = search_facts("revenue recognized", facts, records, taxonomy)
    assert result.partial is True
    assert result.term_residuals == ("recognized",)
    assert result.target_atom == Atom("H_REVENUE")
    assert result.hits


def test_search_unknown_head_returns_empty_partial_result() -> None:
    """An undecomposable term returns no hits and raises nothing."""
    facts, records, taxonomy = _pool()
    result = search_facts("zanzibar", facts, records, taxonomy)
    assert result.hits == ()
    assert result.partial is True
    assert result.target_atom is not None
    assert result.target_atom.head == "H_UNKNOWN"


def test_search_limit_truncates_the_ranked_prefix() -> None:
    """A limit keeps the ranked order's prefix, nothing else."""
    facts, records, taxonomy = _pool()
    full = search_facts("revenue", facts, records, taxonomy)
    limited = search_facts("revenue", facts, records, taxonomy, limit=2)
    assert [hit.qname for hit in limited.hits] == [hit.qname for hit in full.hits[:2]]
