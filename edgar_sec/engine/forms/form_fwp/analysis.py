"""Free writing prospectus review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
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

_RULE_433_RE = re.compile(r"rule\s*433\b", re.IGNORECASE)
_REGISTRATION_RE = re.compile(
    r"registration\s+(?:statement\s+)?nos?\.?[:\s]*"
    r"((?:\d{3}-\d{3,}(?:-\d{2})?[\s,and]*)+)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d{3}-\d{3,}(?:-\d{2})?")
_GUARANTOR_RE = re.compile(r"guarantor:\s+([^\n]+)", re.IGNORECASE)
_GUARANTOR_NEXT_LINE_RE = re.compile(r"guarantor:?\s*\n\s*([^\n]+)", re.IGNORECASE)
_FILE_NUMBER_SHAPE_RE = re.compile(r"\d{3}-\d")

_ISSUER_SKIP_TOKENS: tuple[str, ...] = (
    "free writing prospectus",
    "filed pursuant",
    "registration statement",
    "registration no",
    "subject to completion",
    "prospectus supplement",
    "preliminary",
)


def _issuer_name(lines: list[str]) -> str | None:
    for line in lines[:12]:
        stripped = line.strip()
        if not 3 <= len(stripped) <= 70:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in _ISSUER_SKIP_TOKENS):
            continue
        if "$" in stripped or not stripped[0].isalpha():
            continue
        if _FILE_NUMBER_SHAPE_RE.search(stripped):
            continue
        if not any(token in lowered for token in NAME_FORM_TOKENS):
            continue
        identity = parse_registrant_identity(stripped)
        if identity.name:
            return stripped
    return None


def _form_fwp_fields(text: str, lines: list[str]) -> dict[str, Any]:
    head_text = "\n".join(lines[:30])
    registration_numbers: list[str] = []
    caption = _REGISTRATION_RE.search(head_text)
    if caption is not None:
        registration_numbers = _NUMBER_RE.findall(caption.group(1))
    guarantor = _GUARANTOR_RE.search(head_text) or _GUARANTOR_NEXT_LINE_RE.search(
        head_text
    )
    return {
        "issuer_name": _issuer_name(lines),
        "guarantor_name": guarantor.group(1).strip() if guarantor else None,
        "rule_reference": "433" if _RULE_433_RE.search(head_text) else None,
        "registration_numbers": registration_numbers,
        "cusip": extract_cusip_near_caption(text),
    }


def analyze_form_fwp_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single FWP review case producing header-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "FWP")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="FWP", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()

    fields = _form_fwp_fields(text, lines)
    rep["form_fwp"] = fields

    if not fields["issuer_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuer_name",
                "no issuer name resolved from the FWP header",
            )
        )
    if not fields["rule_reference"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_rule_reference",
                "no Rule 433 reference matched in the FWP header",
            )
        )
    if not fields["registration_numbers"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registration_number",
                "no registration statement number matched in the FWP header",
            )
        )
    return rep


def summarize_form_fwp_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual FWP case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="FWP")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_fwp", {})

    summary["form_fwp_scorecard"] = {
        "issuer_name_count": sum(
            1 for r in case_reports if fields_of(r).get("issuer_name")
        ),
        "guarantor_name_count": sum(
            1 for r in case_reports if fields_of(r).get("guarantor_name")
        ),
        "rule_reference_count": sum(
            1 for r in case_reports if fields_of(r).get("rule_reference")
        ),
        "registration_number_count": sum(
            1 for r in case_reports if fields_of(r).get("registration_numbers")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
    }
    return summary


analyze_case = analyze_form_fwp_review_case
summarize_cases = summarize_form_fwp_cases

__all__ = [
    "analyze_case",
    "analyze_form_fwp_review_case",
    "summarize_cases",
    "summarize_form_fwp_cases",
]
