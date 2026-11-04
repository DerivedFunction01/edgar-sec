"""Form F-3 review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.facing_sheet import facing_sheet_fields


def analyze_form_f3_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single F-3 review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "F-3")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="F-3", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, resolved_form)
    rep["form_f3"] = fields

    if not fields["registration_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registration_number",
                "no registration number matched in the cover header",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover header",
            )
        )
    return rep


def summarize_form_f3_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual F-3 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="F-3")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_f3", {})

    kind_counts: dict[str, int] = {}
    for rep in case_reports:
        kind = fields_of(rep).get("document_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    summary["form_f3_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "registration_number_count": sum(
            1 for r in case_reports if fields_of(r).get("registration_number")
        ),
        "fee_table_count": sum(
            1 for r in case_reports if fields_of(r).get("fee_table_present")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
        "document_kind_counts": kind_counts,
    }
    return summary


analyze_case = analyze_form_f3_review_case
summarize_cases = summarize_form_f3_cases

__all__ = [
    "analyze_case",
    "analyze_form_f3_review_case",
    "summarize_cases",
    "summarize_form_f3_cases",
]
