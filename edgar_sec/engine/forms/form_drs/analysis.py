"""DRS review analysis: banner, base-form dispatch, letter metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.annual.taxonomy import FORM_20F_TYPE
from edgar_sec.domain.forms.families.form_drs.models import DrsKind
from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_ITEMS,
    REGISTRATION_FORM_TYPES,
)
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import RE_FULL_DATE

_BANNER_PHRASES = (
    "as confidentially submitted",
    "confidentially submitted",
    "confidential draft submission",
    "submitted confidentially",
    "has not been publicly filed",
    "has not been filed publicly",
)
_BANNER_RE = re.compile(build_alternation(_BANNER_PHRASES), re.IGNORECASE)
_BASE_FORM_TYPES = REGISTRATION_FORM_TYPES + (FORM_20F_TYPE,)
_FORM_ALT = build_alternation(tuple(t.lower() for t in _BASE_FORM_TYPES))
_BASE_FORM_RE = re.compile(r"\bform\s+(" + _FORM_ALT + r")\b", re.IGNORECASE)
_DRAFT_TITLE_RE = re.compile(
    r"confidential draft submission(?:\s+no\.\s*(\d+))?"
    r"(?:\s+amendment\s+no\.\s*(\d+))?\s+to\s+form\s+(" + _FORM_ALT + r")",
    re.IGNORECASE,
)
_ON_FORM_RE = re.compile(
    r"(?:registration statement|draft submission)\s+on\s+form\s+(" + _FORM_ALT + r")\b",
    re.IGNORECASE,
)
_STATEMENT_PHRASE_RE = re.compile(
    r"draft registration statement|registration statement", re.IGNORECASE
)
_RE_LINE_RE = re.compile(r"^\s*re:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FIRM_SUFFIX_ALT = build_alternation((r"LLP", r"L\.L\.P\.", r"PLLC", r"P\.C\."))
_FIRM_RE = re.compile(r"\b([A-Z][A-Za-z&.,' -]*?(?:" + _FIRM_SUFFIX_ALT + r"))\b")
_HEAD_LINES = 120


def _normalize_form(token: str) -> str:
    return token.strip().upper()


def _base_form_signal(lines: list[str], text: str) -> dict[str, Any]:
    """Base-form signal from the face: the draft-submission title first,
    then an explicit on-Form phrase, then any Form X mention in the head.
    """
    head_text = "\n".join(lines[:_HEAD_LINES])
    title = _DRAFT_TITLE_RE.search(head_text)
    if title:
        return {
            "base_form": _normalize_form(title.group(3)),
            "submission_number": title.group(1),
            "amendment_number": title.group(2),
            "signal": "draft_title",
        }
    on_form = _ON_FORM_RE.search(head_text)
    if on_form:
        return {
            "base_form": _normalize_form(on_form.group(1)),
            "submission_number": None,
            "amendment_number": None,
            "signal": "on_form_phrase",
        }
    mention = _BASE_FORM_RE.search(head_text) or _BASE_FORM_RE.search(text[:4000])
    if mention:
        return {
            "base_form": _normalize_form(mention.group(1)),
            "submission_number": None,
            "amendment_number": None,
            "signal": "head_mention",
        }
    return {
        "base_form": None,
        "submission_number": None,
        "amendment_number": None,
        "signal": None,
    }


def _dispatch_items(base_form: str | None, body_text: str) -> tuple[str | None, int]:
    """Section count when the body is read on the base family's own
    taxonomy — the dispatch proof. Item-less entries fall back to the
    S-1 item set, as the registration cover builder does."""
    if base_form is None:
        return None, 0
    entry = get_family_entry(base_form)
    if entry is None:
        return None, 0
    items = entry.taxonomy_items or FORM_S1_ITEMS
    sequence = detect_section_sequence(
        body_text, family=entry.family, taxonomy_items=items
    )
    return entry.family, len(sequence.sections)


def _letter_metadata(lines: list[str], text: str) -> dict[str, Any]:
    head_text = "\n".join(lines[:_HEAD_LINES])
    re_match = _RE_LINE_RE.search(head_text)
    re_subject = re_match.group(1) if re_match else None
    registrant = None
    if re_subject:
        registrant = _BASE_FORM_RE.sub("", re_subject)
        registrant = _STATEMENT_PHRASE_RE.sub("", registrant).strip(" -–—,")
        registrant = registrant or None
    firm = _FIRM_RE.search(head_text)
    date = RE_FULL_DATE.search(head_text)
    return {
        "re_subject": re_subject,
        "registrant": registrant,
        "counsel": firm.group(1).strip() if firm else None,
        "letter_date": date.group(0) if date else None,
    }


def analyze_drs_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single DRS review case producing wrapper diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "DRS")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="DRS", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    kind = (
        DrsKind.LETTER
        if resolved_form.strip().upper() == "DRSLTR"
        else DrsKind.SUBMISSION
    )
    head_text = "\n".join(lines[:_HEAD_LINES])
    signal = _base_form_signal(lines, text)
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    body_text = "\n".join(lines[end:]) if end else text
    base_family, dispatch_items = _dispatch_items(signal["base_form"], body_text)

    fields: dict[str, Any] = {
        "kind": kind.value,
        "banner_present": bool(_BANNER_RE.search(head_text)),
        "base_form": signal["base_form"],
        "base_signal": signal["signal"],
        "base_family": base_family,
        "dispatch_item_count": dispatch_items,
        "submission_number": signal["submission_number"],
        "amendment_number": signal["amendment_number"],
    }
    if kind is DrsKind.LETTER:
        fields.update(_letter_metadata(lines, text))
    rep["form_drs"] = fields

    if kind is DrsKind.SUBMISSION and not fields["banner_present"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_banner",
                "no confidential-submission banner phrase matched in the head",
            )
        )
    if not fields["base_form"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_base_form",
                "no base-form signal matched on the document face",
            )
        )
    return rep


def summarize_drs_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual DRS case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="DRS")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_drs", {})

    base_form_counts: dict[str, int] = {}
    for rep in case_reports:
        base = fields_of(rep).get("base_form")
        if base:
            base_form_counts[base] = base_form_counts.get(base, 0) + 1

    summary["form_drs_scorecard"] = {
        "kind_counts": {
            kind: sum(1 for r in case_reports if fields_of(r).get("kind") == kind)
            for kind in ("submission", "letter")
        },
        "banner_count": sum(
            1 for r in case_reports if fields_of(r).get("banner_present")
        ),
        "base_form_counts": base_form_counts,
        "dispatch_proof_count": sum(
            1 for r in case_reports if fields_of(r).get("dispatch_item_count")
        ),
        "registrant_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant")
        ),
        "counsel_count": sum(1 for r in case_reports if fields_of(r).get("counsel")),
        "letter_date_count": sum(
            1 for r in case_reports if fields_of(r).get("letter_date")
        ),
    }
    return summary


analyze_case = analyze_drs_review_case
summarize_cases = summarize_drs_cases

__all__ = [
    "analyze_case",
    "analyze_drs_review_case",
    "summarize_cases",
    "summarize_drs_cases",
]
