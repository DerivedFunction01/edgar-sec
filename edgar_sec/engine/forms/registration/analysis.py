"""Registration statement review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.analysis import analyze_form_case, summarize_form_cases


def analyze_registration_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single registration review case directory producing diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "S-1")
    resolved_family = str(record.get("family") or resolved_form)
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family=resolved_family
    )
    if rep is None:
        return None
    cm = rep["checkmarks"]
    states = cm.get("candidate_states", {})
    cm["rule_415"] = states.get("rule_415") == "checked"
    cm["rule_462b"] = states.get("rule_462b") == "checked"
    cm["egc_opt_out"] = states.get("egc_opt_out") == "checked"
    return rep


def summarize_registration_cases(
    case_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate individual registration case analyses into an overall summary."""
    family = case_reports[0].get("family", "S-1") if case_reports else "S-1"
    summary = summarize_form_cases(case_reports, family=family)
    if summary.get("case_count", 0) == 0:
        return summary
    rule_415_hits = sum(
        1 for r in case_reports if r.get("checkmarks", {}).get("rule_415")
    )
    rule_462b_hits = sum(
        1 for r in case_reports if r.get("checkmarks", {}).get("rule_462b")
    )
    egc_opt_out_hits = sum(
        1 for r in case_reports if r.get("checkmarks", {}).get("egc_opt_out")
    )
    cm_sc = summary.setdefault("checkmark_scorecard", {})
    cm_sc["rule_415_count"] = rule_415_hits
    cm_sc["rule_462b_count"] = rule_462b_hits
    cm_sc["egc_opt_out_count"] = egc_opt_out_hits
    return summary


analyze_case = analyze_registration_review_case
summarize_cases = summarize_registration_cases

__all__ = [
    "analyze_case",
    "analyze_registration_review_case",
    "summarize_cases",
    "summarize_registration_cases",
]
