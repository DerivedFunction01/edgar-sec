"""Form F-6 review analysis: dual-party cover fields and scorecard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.facing_sheet import facing_sheet_fields
from edgar_sec.engine.tables.protection.tags import find_table_spans
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity

_ISSUER_CAPTION = "exact name of issuer of deposited securities"
_DEPOSITARY_CAPTION = "exact name of depositary"
_RULE_466_KEYS: tuple[str, ...] = ("rule_466_immediate", "rule_466_deferred")


def _name_above(lines: list[str], idx: int) -> str | None:
    """The name printed above a caption, skipping blanks and rules."""
    seen = 0
    for above in range(idx - 1, max(idx - 8, -1), -1):
        candidate = lines[above].strip()
        if not candidate or set(candidate) <= set("-=*_ "):
            continue
        seen += 1
        identity = parse_registrant_identity(candidate)
        if identity.name:
            return identity.name
        if seen >= 2:
            return None
    return None


def _party_name(lines: list[str], caption: str) -> str | None:
    """The party name at its exact-name caption: on the caption line
    itself in era layouts, on the line above it in modern ones.
    """
    for idx, line in enumerate(lines[:100]):
        pos = line.lower().find(caption)
        if pos < 0:
            continue
        segment = line[:pos].strip().rstrip("(").strip()
        if segment:
            identity = parse_registrant_identity(segment)
            if identity.name:
                return identity.name
            if len(segment) <= 80 and "exact name" not in segment.lower():
                return segment
        return _name_above(lines, idx)
    return None


def _translated_issuer_name(lines: list[str]) -> str | None:
    """The issuer name at its translation caption, where a cover
    prints no exact-name caption for the issuer at all.
    """
    caption = "translation of issuer's name into english"
    for idx, line in enumerate(lines[:100]):
        pos = line.lower().find(caption)
        if pos < 0:
            continue
        segment = line[:pos].split("(")[0].strip()
        if segment:
            identity = parse_registrant_identity(segment)
            return identity.name or segment
        return _name_above(lines, idx)
    return None


def analyze_form_f6_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single F-6 review case producing cover diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "F-6")
    family = resolve_alias(resolved_form) or resolved_form
    rep = analyze_form_case(case_dir, record, form=resolved_form, family=family)
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family=family)
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, resolved_form)
    fields["issuer_name"] = _party_name(
        lines, _ISSUER_CAPTION
    ) or _translated_issuer_name(lines)
    fields["depositary_name"] = _party_name(lines, _DEPOSITARY_CAPTION)
    checked = set(rep["checkmarks"]["checked_keys"])
    fields["rule_466_decision"] = sorted(checked.intersection(_RULE_466_KEYS))
    fields["separate_registration_statement"] = (
        "separate_registration_statement" in checked
    )
    rep["form_f6"] = fields

    if not fields["issuer_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuer_name",
                "no issuer name resolved above the deposited-securities caption",
            )
        )
    if not fields["depositary_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_depositary_name",
                "no depositary name resolved above the depositary caption",
            )
        )
    if not fields["registration_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registration_number",
                "no registration number matched in the cover header",
            )
        )
    if not fields["rule_466_decision"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_rule_466_decision",
                "no Rule 466 effectiveness box resolved as checked",
            )
        )
    return rep


def summarize_form_f6_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual F-6 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="F-6")
    total = summary.get("case_count", 0)
    if not total:
        return summary
    per_family: dict[str, dict[str, Any]] = {}
    for rep in case_reports:
        bucket = per_family.setdefault(
            rep["family"],
            {
                "case_count": 0,
                "issuer_name_count": 0,
                "depositary_name_count": 0,
                "registration_number_count": 0,
                "fee_table_count": 0,
                "rule_466_decision_count": 0,
                "decision_counts": {},
                "document_kind_counts": {},
            },
        )
        fields = rep.get("form_f6", {})
        bucket["case_count"] += 1
        bucket["issuer_name_count"] += bool(fields.get("issuer_name"))
        bucket["depositary_name_count"] += bool(fields.get("depositary_name"))
        bucket["registration_number_count"] += bool(fields.get("registration_number"))
        bucket["fee_table_count"] += bool(fields.get("fee_table_present"))
        bucket["rule_466_decision_count"] += bool(fields.get("rule_466_decision"))
        for key in fields.get("rule_466_decision", []):
            counts = bucket["decision_counts"]
            counts[key] = counts.get(key, 0) + 1
        kind = fields.get("document_kind")
        if kind:
            kinds = bucket["document_kind_counts"]
            kinds[kind] = kinds.get(kind, 0) + 1
    summary["form_f6_scorecard"] = per_family
    return summary


analyze_case = analyze_form_f6_review_case
summarize_cases = summarize_form_f6_cases

__all__ = [
    "analyze_case",
    "analyze_form_f6_review_case",
    "summarize_cases",
    "summarize_form_f6_cases",
]
