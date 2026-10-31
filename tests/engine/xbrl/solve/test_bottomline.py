"""Tests for bottomline candidate selection from atom coordinates."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.bottomline import (
    bottomline_candidate,
    bottomline_rank,
    is_bottomline,
)

_ACC = AccessionNumber("0000000000-25-000001")


def test_is_bottomline_marks_net_modifier_and_bare_income() -> None:
    """The net modifier marks any head; a bare income head marks itself."""
    assert is_bottomline(Atom("H_INCOME", frozenset({"M_NET_BOTTOMLINE"})))
    assert is_bottomline(Atom("H_INCOME"))
    assert not is_bottomline(Atom("H_INCOME", frozenset({"M_GROSS"})))
    assert not is_bottomline(Atom("H_REVENUE", frozenset({"V_NET"})))


def test_bottomline_rank_rejects_slices_and_comprehensive() -> None:
    """EPS slices and comprehensive-income atoms are not candidates."""
    diluted = Atom("H_INCOME", frozenset({"M_NET_BOTTOMLINE", "V_DILUTED"}))
    assert bottomline_rank(diluted, "us-gaap:NetIncomeLoss") is None
    oci = Atom("H_INCOME", frozenset({"M_NET_BOTTOMLINE", "M_OCI"}))
    assert bottomline_rank(oci, "us-gaap:NetIncomeLoss") is None
    assert bottomline_rank(None, "us-gaap:NetIncomeLoss") is None


def test_bottomline_candidate_prefers_net_modifier() -> None:
    """The net-modifier candidate outranks a bare income head."""
    atoms = {
        "us-gaap:ProfitLoss": Atom("H_INCOME"),
        "us-gaap:NetIncomeLoss": Atom("H_INCOME", frozenset({"M_NET_BOTTOMLINE"})),
    }
    facts = [
        XbrlFact(
            _ACC,
            qname,
            1.0,
            period_type="duration",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        for qname in atoms
    ]
    arcs = [CalculationArc("us-gaap:ProfitLoss", "us-gaap:NetIncomeLoss", 1.0)]
    assert bottomline_candidate(atoms, facts, arcs) == "us-gaap:NetIncomeLoss"
