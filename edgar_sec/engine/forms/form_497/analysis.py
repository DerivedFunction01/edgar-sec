"""Form 497 review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import (
    NAME_FORM_TOKENS,
    extract_cusip_near_caption,
)
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity

_RULE_497_RE = re.compile(r"rule\s*497\s*\(\s*([a-z])\s*\)", re.IGNORECASE)
_REGISTRATION_RE = re.compile(
    r"registration\s+(?:statement\s+)?no\.?\s*:?\s*((?:\d{3}-\d{3,}(?:-\d{2})?))",
    re.IGNORECASE,
)
_KIND_TERMS: tuple[tuple[str, str], ...] = (
    ("prospectus supplement", "prospectus_supplement"),
    ("statement of additional information", "statement_of_additional_information"),
    ("prospectus", "prospectus"),
)

_SKIP_TOKENS: tuple[str, ...] = (
    "filed pursuant",
    "registration no",
    "registration statement",
    "prospectus supplement",
    "prospectus",
    "subject to completion",
)


def _registrant_name(lines: list[str]) -> str | None:
    for line in lines[:20]:
        stripped = line.strip()
        if not 3 <= len(stripped) <= 80:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in _SKIP_TOKENS):
            continue
        if "$" in stripped or not stripped[0].isalpha():
            continue
        if not any(token in lowered for token in NAME_FORM_TOKENS):
            continue
        identity = parse_registrant_identity(stripped)
        if identity.name:
            return stripped
    return None


def _form_497_fields(text: str, lines: list[str]) -> dict[str, Any]:
    head_text = "\n".join(lines[:40])
    lowered_head = head_text.lower()
    kind = None
    for term, label in _KIND_TERMS:
        if term in lowered_head:
            kind = label
            break
    rule = _RULE_497_RE.search(head_text)
    registration = _REGISTRATION_RE.search(head_text)
    return {
        "registrant_name": _registrant_name(lines),
        "rule_reference": f"497({rule.group(1).lower()})" if rule else None,
        "registration_numbers": [registration.group(1)] if registration else [],
        "document_kind": kind,
        "cusip": extract_cusip_near_caption(text),
    }


def analyze_form_497_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single 497 review case producing header diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "497")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="497", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    fields = _form_497_fields(text, lines)
    rep["form_497"] = fields

    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the 497 header",
            )
        )
    if not fields["document_kind"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_document_kind",
                "no prospectus document kind matched in the 497 header",
            )
        )
    return rep


def summarize_form_497_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual 497 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="497")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_497", {})

    summary["form_497_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "rule_reference_count": sum(
            1 for r in case_reports if fields_of(r).get("rule_reference")
        ),
        "registration_number_count": sum(
            1 for r in case_reports if fields_of(r).get("registration_numbers")
        ),
        "document_kind_count": sum(
            1 for r in case_reports if fields_of(r).get("document_kind")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
    }
    return summary


analyze_case = analyze_form_497_review_case
summarize_cases = summarize_form_497_cases

__all__ = [
    "analyze_case",
    "analyze_form_497_review_case",
    "summarize_cases",
    "summarize_form_497_cases",
]
