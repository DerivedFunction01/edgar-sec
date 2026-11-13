"""Population labeller: alignment method pins (maps, gates, signatures)."""

from __future__ import annotations

from tools.table_extraction_corpus.label import (
    apply_aligned_negative,
    cell_digits,
    label_geometries,
    role_family,
    schedule_family,
    score_geometry,
    sig_digits,
    statement_candidates,
)


def test_sig_digits_is_scale_free() -> None:
    """Values printed in thousands match as-filed facts at any scale."""
    assert sig_digits(1234000) == sig_digits("1,234") == "1234"
    assert sig_digits(0) is None
    assert sig_digits(42) is None
    assert sig_digits(True) is None
    assert sig_digits("not a number") is None


def test_cell_digits_excludes_bare_years() -> None:
    """A bare year cell is never alignment evidence."""
    assert cell_digits("2024") is None
    assert cell_digits("$1,234") == "1234"
    assert cell_digits("—") is None


def test_role_family_statement_and_group_maps() -> None:
    """Statement titles label directly; note titles map to groups."""
    assert role_family("Consolidated Balance Sheets", "statement") == (
        "balance_sheet",
        None,
    )
    assert role_family("Consolidated Statements of Operations", "statement") == (
        "income_statement",
        None,
    )
    assert role_family("Income Taxes", "note") == (None, "tax")
    assert role_family("Document and Entity Information", "document") == (None, None)


def test_role_family_comprehensive_income_maps_to_nothing() -> None:
    """Comprehensive-income-only roles deliberately earn no label."""
    assert role_family("Statement of Comprehensive Income", "statement") == (
        None,
        None,
    )
    assert role_family(
        "Consolidated Statements of Operations and Comprehensive Income",
        "statement",
    ) == ("income_statement", None)


def test_schedule_family_signatures() -> None:
    """Each group's structural signature, positive and negative."""
    years = (("2025", "100"), ("2026", "200"), ("Thereafter", "300"))
    assert schedule_family("debt", years) == "debt_maturity"
    assert schedule_family("debt", (("Total debt", "600"),)) is None
    assert schedule_family("tax", (("Deferred tax assets", "5"),)) == "deferred_tax"
    rate = (("Statutory federal rate", "21.0%"), ("Effective rate", "19.0%"))
    assert schedule_family("tax", rate) == "tax_reconciliation"
    levels = (("Level 1", "10"), ("Level 2", "20"), ("Total", "30"))
    assert schedule_family("fair_value", levels) == "fair_value"
    eps = (("Basic", "1.0"), ("Diluted", "0.9"))
    assert schedule_family("eps", eps) == "eps_reconciliation"
    assert schedule_family("labor", years) is None


def test_score_geometry_counts_matches_and_label_hits() -> None:
    """Score is matched/total digits; hits count rows sharing >= 2 tokens."""
    rows = (("Total assets", "1,234"), ("Cash", "567"))
    digits = frozenset({"1234", "567"})
    tokens = frozenset({"total", "assets", "cash"})
    score, hits = score_geometry(rows, digits, tokens)
    assert score == 1.0
    assert hits == 1
    score, _ = score_geometry(rows, frozenset({"999"}), tokens)
    assert score == 0.0


def _role(title: str, family, group, rows: list[dict]) -> dict:
    return {"title": title, "family": family, "group": group, "rows": rows}


def test_label_geometries_aligned_statement() -> None:
    """A geometry matching a statement role takes the family, aligned."""
    geo = {
        "table_index": 1,
        "rows": [["Total assets", "1,234"], ["Total liabilities", "567"]],
    }
    role = _role(
        "Consolidated Balance Sheets",
        "balance_sheet",
        None,
        [
            {"label": "Total assets", "values": [1234]},
            {"label": "Total liabilities", "values": [567]},
        ],
    )
    (label,) = label_geometries([geo], [role])
    assert label["family"] == "balance_sheet"
    assert label["provenance"] == "aligned"
    assert label["score"] == 1.0


def test_label_geometries_gate_refuses_weak_match() -> None:
    """Below the 0.60 gate the geometry stays unlabelled, with a reason."""
    geo = {"table_index": 1, "rows": [["Total assets", "9,999"]]}
    role = _role(
        "Consolidated Balance Sheets",
        "balance_sheet",
        None,
        [{"label": "Total assets", "values": [1234]}],
    )
    (label,) = label_geometries([geo], [role])
    assert label["family"] is None
    assert label["reason"] == "no_alignment"


def test_label_geometries_signature_and_unresolved() -> None:
    """Group alignment resolves through the signature, or queues."""
    debt_geo = {
        "table_index": 1,
        "rows": [
            ["2025", "1,234"],
            ["2026", "2,345"],
            ["Thereafter", "3,456"],
            ["Long-term debt", "7,035"],
            ["Debt maturities total", "7,035"],
        ],
    }
    plain_geo = {"table_index": 2, "rows": [["Notes payable", "100"]]}
    role = _role(
        "Long-term Debt",
        None,
        "debt",
        [
            {"label": "Long-term debt", "values": [7035]},
            {"label": "Debt maturities thereafter", "values": [1234, 2345, 3456]},
        ],
    )
    plain_role = _role(
        "Long-term Debt",
        None,
        "debt",
        [{"label": "Notes payable", "values": [100]}],
    )
    debt_label, plain_label = label_geometries(
        [debt_geo, plain_geo], [role, plain_role]
    )
    assert debt_label["family"] == "debt_maturity"
    assert debt_label["provenance"] == "signature"
    assert plain_label["family"] is None


def test_apply_aligned_negative() -> None:
    """XBRL present + no alignment >= 0.25 means other, by the teacher."""
    labels = [{"family": None, "provenance": None, "reason": "no_alignment"}]
    out = apply_aligned_negative([dict(labels[0])], is_xbrl=True)
    assert out[0]["family"] == "other"
    assert out[0]["provenance"] == "aligned_negative"
    out = apply_aligned_negative([dict(labels[0])], is_xbrl=False)
    assert out[0]["family"] is None
    assert out[0]["reason"] == "no_xbrl"


def test_statement_candidates_propose_only() -> None:
    """Unlabelled statement-shaped geometries become candidates."""
    geo = {
        "table_index": 3,
        "rows": [["Total revenues", "500"], ["Net income", "50"]],
    }
    labels = [{"table_index": 3, "family": None}]
    candidates = statement_candidates([geo], labels)
    assert candidates[0]["candidate"] == "income_statement"
    labels = [{"table_index": 3, "family": "cash_flow"}]
    assert statement_candidates([geo], labels) == []
