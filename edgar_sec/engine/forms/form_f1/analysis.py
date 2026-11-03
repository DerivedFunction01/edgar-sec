"""Forms F-1/F-2 review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.facing_sheet import facing_sheet_fields


def analyze_form_f1_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single F-1/F-2 review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "F-1")
    resolved_family = str(record.get("family") or resolve_alias(resolved_form) or "F-1")
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family=resolved_family
    )
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, resolved_form)
    rep["form_f1"] = fields

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


def summarize_form_f1_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual F-1/F-2 case analyses into an overall summary."""
    family = case_reports[0].get("family", "F-1") if case_reports else "F-1"
    summary = summarize_form_cases(case_reports, family=family)
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_f1", {})

    kind_counts: dict[str, int] = {}
    for rep in case_reports:
        kind = fields_of(rep).get("document_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    summary["form_f1_scorecard"] = {
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


analyze_case = analyze_form_f1_review_case
summarize_cases = summarize_form_f1_cases

__all__ = [
    "analyze_case",
    "analyze_form_f1_review_case",
    "summarize_cases",
    "summarize_form_f1_cases",
]
