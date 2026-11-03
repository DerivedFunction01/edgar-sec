"""Prospectus review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_424b.taxonomy import (
    FORM_424B_DOCUMENT_KINDS,
)
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import CUSIP_RE, is_valid_cusip
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity
from edgar_sec.foundation.regex.builder import build_alternation

_RULE_RE = re.compile(
    r"rule\s*424\s*\(\s*([ab])\s*\)\s*(?:\(\s*(\d)\s*\))?", re.IGNORECASE
)
_REGISTRATION_CAPTION_ALT = build_alternation(
    (
        r"registration\s+(?:statement\s+)?"
        + build_alternation(("no", "nos", "number"))
        + r"\.?",
        r"file\s+no\.",
    )
)
_REGISTRATION_RE = re.compile(
    r"(?:" + _REGISTRATION_CAPTION_ALT + r")[:\s]*(\d{3}-\d{3,})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"\$\s*([0-9][0-9,]{2,}(?:\.[0-9]{2})?)")
_SHARES_RE = re.compile(r"([0-9][0-9,]{2,})\s+shares\b", re.IGNORECASE)
_NAME_SUFFIX_ALT = build_alternation(
    (
        "Corporation",
        r"Corp\.",
        r"Inc\.",
        "LLC",
        r"L\.L\.C\.",
        "Company",
        r"Co\.",
        "Bank",
        "PLC",
        "Trust",
        "Partners",
        "Holdings",
        "Group",
        "Fund",
    )
)
_OF_NAME_RE = re.compile(
    r"\bof\s+([A-Z][A-Za-z0-9&.,'\u2019\- ]{2,60}?(?:" + _NAME_SUFFIX_ALT + r"))\b"
)
_TRAILING_NUMBER_RE = re.compile(r"\s\d+$")

_TITLE_SKIP_TOKENS: tuple[str, ...] = (
    "prospectus",
    "registration",
    "filed pursuant",
    "shares",
    "supplement",
    "preliminary",
    "table of",
    "securities and exchange",
    "washington",
    "subject to completion",
)


def _rule_reference(text: str) -> str | None:
    match = _RULE_RE.search(text)
    if match is None:
        return None
    letter = match.group(1).lower()
    number = match.group(2)
    if number:
        return f"424({letter})({number})"
    return f"424({letter})"


def _registration_number(text: str) -> str | None:
    match = _REGISTRATION_RE.search(text)
    return match.group(1) if match else None


def _document_kind(lines: list[str]) -> str | None:
    for line in lines[:40]:
        stripped = line.strip()
        if len(stripped) > 80:
            continue
        lowered = stripped.lower()
        for kind, phrases in FORM_424B_DOCUMENT_KINDS:
            if any(phrase in lowered for phrase in phrases):
                return kind
    return None


_TITLE_NAME_TOKENS: tuple[str, ...] = (
    " inc",
    " corp",
    " llc",
    " company",
    " bank",
    " trust",
    " plc",
    " ltd",
    " partners",
    " holdings",
    " group",
    " fund",
)


_TITLE_CLASS_SUFFIXES: tuple[str, ...] = (
    " common stock",
    " preferred stock",
    " ordinary shares",
    " depositary shares",
)


_PERIOD_TOKEN_RE = re.compile(r"([A-Za-z]+)\.\s")


def _validate_of_name(raw: str) -> str | None:
    name = " ".join(raw.split())
    if " of " in name:
        name = name.rsplit(" of ", 1)[1]
    if len(name) < 3 or "(" in name or '"' in name:
        return None
    for match in _PERIOD_TOKEN_RE.finditer(name):
        token = match.group(1).lower()
        if len(token) > 1 and token not in ("inc", "corp", "co", "ltd"):
            return None
    return name


def _registrant_name(lines: list[str]) -> str | None:
    for line in lines[:40]:
        stripped = line.strip()
        if not 3 <= len(stripped) <= 60:
            continue
        if len(stripped.split()) > 6:
            continue
        if _TRAILING_NUMBER_RE.search(stripped):
            continue
        lowered = stripped.lower()
        for suffix in _TITLE_CLASS_SUFFIXES:
            if lowered.endswith(suffix):
                stripped = stripped[: -len(suffix)].strip()
                lowered = stripped.lower()
                break
        if stripped.endswith(".") and not lowered.endswith(
            ("inc.", "corp.", "co.", "l.l.c.", "ltd.")
        ):
            continue
        if any(token in lowered for token in _TITLE_SKIP_TOKENS):
            continue
        if "$" in stripped or not stripped[0].isalpha():
            continue
        if not any(token in lowered for token in _TITLE_NAME_TOKENS):
            continue
        identity = parse_registrant_identity(stripped)
        if identity.name:
            return identity.name
    flat_head = " ".join("\n".join(lines[:80]).split())
    for match in _OF_NAME_RE.finditer(flat_head):
        name = _validate_of_name(match.group(1))
        if name is not None:
            return name
    return None


def _cusip(cover_text: str) -> str | None:
    lowered = cover_text.lower()
    position = lowered.find("cusip")
    while position != -1:
        window = cover_text[position : position + 48]
        for match in CUSIP_RE.finditer(window):
            candidate = match.group(0)
            if any(ch.isdigit() for ch in candidate) and is_valid_cusip(candidate):
                return candidate.upper()
        position = lowered.find("cusip", position + 1)
    return None


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _form_424b_fields(cover_text: str, lines: list[str]) -> dict[str, Any]:
    header_text = cover_text if len(cover_text.splitlines()) >= 4 else ""
    head_text = "\n".join(lines[:120])
    primary = header_text or head_text
    return {
        "rule_reference": _rule_reference(primary) or _rule_reference(head_text),
        "registration_number": _registration_number(primary)
        or _registration_number(head_text),
        "document_kind": _document_kind(lines),
        "registrant_name": _registrant_name(lines),
        "offering_amount": _first_group(_AMOUNT_RE, primary),
        "share_count": _first_group(_SHARES_RE, primary),
        "cusip": _cusip(primary),
    }


def analyze_form_424b_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single prospectus review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "424B")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="424B")
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

    fields = _form_424b_fields(cover_text, lines)
    rep["form_424b"] = fields

    if not fields["rule_reference"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_rule_reference",
                "no Rule 424(b)/(a) reference matched in the cover header",
            )
        )
    if not fields["registration_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registration_number",
                "no registration statement number matched in the cover header",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover header",
            )
        )
    if not fields["document_kind"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_document_kind",
                "no prospectus document kind title matched in the cover header",
            )
        )
    return rep


def summarize_form_424b_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual prospectus case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="424B")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_424b", {})

    kind_counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    for rep in case_reports:
        kind = fields_of(rep).get("document_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        rule = fields_of(rep).get("rule_reference")
        if rule:
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

    summary["form_424b_scorecard"] = {
        "rule_reference_count": sum(
            1 for r in case_reports if fields_of(r).get("rule_reference")
        ),
        "registration_number_count": sum(
            1 for r in case_reports if fields_of(r).get("registration_number")
        ),
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "offering_amount_count": sum(
            1 for r in case_reports if fields_of(r).get("offering_amount")
        ),
        "share_count_count": sum(
            1 for r in case_reports if fields_of(r).get("share_count")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
        "document_kind_counts": kind_counts,
        "rule_reference_counts": rule_counts,
    }
    return summary


analyze_case = analyze_form_424b_review_case
summarize_cases = summarize_form_424b_cases

__all__ = [
    "analyze_case",
    "analyze_form_424b_review_case",
    "summarize_cases",
    "summarize_form_424b_cases",
]
