"""View summaries for the statement-view driver."""

from __future__ import annotations

from typing import Any


def _statement_summary(view: Any) -> dict[str, Any]:
    """Graph-shape summary of one composed statement view."""
    graph = view.graph
    valued = sum(1 for node in graph.nodes.values() if node.value is not None)
    return {
        "status": str(view.status),
        "message": view.message,
        "root": graph.root_qname or None,
        "nodes": len(graph.nodes),
        "valued_nodes": valued,
        "years": list(view.years),
    }


def _equity_summary(view: Any) -> dict[str, Any]:
    """Opening/closing/component summary of the equity rollforward."""
    return {
        "opening": view.opening,
        "closing": view.closing,
        "components": len(view.components),
        "antichain_members": len(view.antichain_members),
        "populated": view.closing is not None or len(view.components) > 0,
    }


def _topic_summary(name: str, view: Any) -> dict[str, Any]:
    """Disclosure-view summary; populated names content over absence."""
    if name == "derivatives":
        return {
            "notional_amount": view.notional_amount,
            "gross_assets": view.gross_assets,
            "net_assets": view.net_assets,
            "positions": len(view.positions),
            "risk_categories": len(view.risk_categories),
            "populated": view.notional_amount is not None or len(view.positions) > 0,
        }
    if name == "debt":
        return {
            "total_debt": view.total_debt,
            "current_debt": view.current_debt,
            "long_term_debt": view.long_term_debt,
            "maturities": len(view.maturities),
            "populated": view.total_debt is not None or len(view.maturities) > 0,
        }
    if name == "cash_rollforward":
        return {
            "beginning": view.beginning,
            "net_change": view.net_change,
            "end": view.end,
            "rollforward_verified": view.rollforward_verified,
            "populated": view.end is not None or view.beginning is not None,
        }
    if name == "fair_value_hierarchy":
        rows = view.rows
        return {
            "rows": len(rows),
            "verified": sum(1 for row in rows if row.verified is True),
            "discrepancy": sum(1 for row in rows if row.verified is False),
            "unverified": sum(1 for row in rows if row.verified is None),
            "populated": len(rows) > 0,
        }
    if name == "level3_rollforward":
        return {
            "opening": view.opening,
            "closing": view.closing,
            "populated": view.closing is not None or view.opening is not None,
        }
    if name == "pension_funded_status":
        return {
            "assets_closing": view.assets_closing,
            "obligation_closing": view.obligation_closing,
            "assets_verified": view.assets_verified,
            "obligation_verified": view.obligation_verified,
            "populated": (
                view.assets_closing is not None or view.obligation_closing is not None
            ),
        }
    if name == "segment_breakdown":
        graph = view.graph
        record = graph.classification
        return {
            "concept": view.concept_qname,
            "axis": view.axis_qname,
            "total": view.total,
            "members": len(view.members),
            "verified": view.verified,
            "classification": None if record is None else record.kind,
            "basis": None if record is None else record.basis,
            "alternates": len(graph.alternates),
            "filed_member_sum": graph.filed_member_sum,
            "populated": view.total is not None or len(view.members) > 0,
        }
    raise ValueError(f"no topic summary for {name!r}")
