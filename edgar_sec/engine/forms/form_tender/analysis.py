"""Tender offer review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.form_tender.models import TenderKind
from edgar_sec.domain.forms.families.form_tender.taxonomy import (
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_TO_ITEMS,
    TENDER_TAXONOMY_BY_KIND,
)
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import parse_cusip
from edgar_sec.engine.forms.cover.registrant import previous_content_line
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.tables.protection.tags import find_table_spans

_DESIGNATION_KEYS = (
    "third_party_tender_offer",
    "issuer_tender_offer",
    "going_private_transaction",
    "schedule_13d_amendment",
)
_MARK_KEYS = (
    "fee_offset_rule_0_11",
    "preliminary_communications",
    "final_amendment",
    "cross_border_issuer_tender_offer",
    "cross_border_third_party_tender_offer",
    "connection_solicitation_materials",
    "connection_registration_statement",
    "preliminary_solicitation_copies",
)

_FORM_KINDS: dict[str, TenderKind] = {
    "SC 13E4": TenderKind.ISSUER_TENDER_PREDECESSOR,
    "SC 13E4/A": TenderKind.ISSUER_TENDER_PREDECESSOR,
    "SC 14D1": TenderKind.THIRD_PARTY_PREDECESSOR,
    "SC 14D1/A": TenderKind.THIRD_PARTY_PREDECESSOR,
    "SC14D1F": TenderKind.FOREIGN_NOTICE,
    "SC14D1F/A": TenderKind.FOREIGN_NOTICE,
    "SC 14D9": TenderKind.SOLICITATION,
    "SC 14D9/A": TenderKind.SOLICITATION,
    "SC14D9C": TenderKind.SOLICITATION,
    "SC14D9F": TenderKind.SOLICITATION,
    "SC14D9F/A": TenderKind.SOLICITATION,
    "SC 13E3": TenderKind.GOING_PRIVATE,
    "SC 13E3/A": TenderKind.GOING_PRIVATE,
}

_SUBJECT_CAPTION_RE = re.compile(
    r"\(name of (the |of the )?(subject company|issuer)"
    r"|\(exact name of (the )?(subject company|issuer|registrant)",
    re.IGNORECASE,
)
_FILING_PERSON_CAPTION_RE = re.compile(
    r"\(names? of filing persons?"
    r"|^\s*names? of filing persons?"
    r"|\(name of filing person"
    r"|\(name of person\s*\(s\)\s*filing statement"
    r"|\(name\(s\) of person\(s\) filing statement"
    r"|\(name of person filing statement"
    r"|\(names? of persons? filing statement"
    r"|\(name of issuer and\s+person\s+filing statement"
    r"|\(bidders?\)"
    r"|\(offerors?\)"
    r"|issuer and offeror",
    re.IGNORECASE,
)
_CUSIP_CAPTION_RE = re.compile(r"\(cusip number", re.IGNORECASE)
_COMBINED_FILER_RE = re.compile(r"and filing person", re.IGNORECASE)
_KNOWN_CAPTION_RE = re.compile(
    r"\(name of |\(exact name of |\(names? of |\(title of class"
    r"|\(cusip number|\(name, address",
    re.IGNORECASE,
)
_CLASS_CAPTION_RE = re.compile(r"\(title of class of securities", re.IGNORECASE)
_NOTICE_CAPTION_RE = re.compile(
    r"persons?(\(s\))?\s+authorized\s+to\s+receive\s+notices?", re.IGNORECASE
)
_FEE_TABLE_RE = re.compile(r"calculation\s+of\s+filing\s+fee", re.IGNORECASE)
_SCHEDULE_TO_TITLE_RE = re.compile(r"^\s*schedule\s+to\s*$", re.IGNORECASE)
_SCHEDULE_13E3_TITLE_RE = re.compile(r"^\s*schedule\s+13e-3\s*$", re.IGNORECASE)
_OFFER_TO_PURCHASE_RE = re.compile(
    r"offer to purchase[\s\S]{0,240}?exhibit"
    r"|exhibit[\s\S]{0,240}?offer to purchase",
    re.IGNORECASE,
)
_TRANSMITTAL_RE = re.compile(
    r"letter of transmittal[\s\S]{0,240}?exhibit"
    r"|exhibit[\s\S]{0,240}?letter of transmittal",
    re.IGNORECASE,
)
_CAPTION_LINE_RE = re.compile(r"^\s*\(.*\)\s*$")
_HEAD_LINES = 80


def _accession_year(accession: str) -> int | None:
    parts = accession.split("-")
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    yy = int(parts[1])
    return 1900 + yy if yy >= 90 else 2000 + yy


def _classify_kind(form: str, lines: list[str]) -> TenderKind:
    kind = _FORM_KINDS.get(form.strip().upper())
    if kind is not None:
        return kind
    return TenderKind.SCHEDULE_TO


def _taxonomy_for(
    kind: TenderKind, lines: list[str], accession: str
) -> tuple[ItemDefinition, ...]:
    if kind is not TenderKind.GOING_PRIVATE:
        return TENDER_TAXONOMY_BY_KIND[kind]
    head = lines[:_HEAD_LINES]
    if any(_SCHEDULE_TO_TITLE_RE.match(line) for line in head):
        return SCHEDULE_TO_ITEMS
    if any(_SCHEDULE_13E3_TITLE_RE.match(line) for line in head):
        year = _accession_year(accession)
        if year is not None and year < 2000:
            return SCHEDULE_13E3_PRIOR_ITEMS
        return SCHEDULE_13E3_ITEMS
    return SCHEDULE_13E3_ITEMS


def _value_above_caption(
    lines: list[str], caption_re: re.Pattern[str], *, max_lines: int = 1
) -> tuple[str, ...]:
    """Value text for a caption: the same-line prefix when the caption
    shares its line, else the content lines immediately above it."""
    for index, line in enumerate(lines):
        match = caption_re.search(line)
        if match is None:
            continue
        prefix = line[: match.start()].strip(" ,-(")
        if len(prefix) >= 3 and not _CAPTION_LINE_RE.match(prefix):
            return (prefix,)
        values: list[str] = []
        cursor = index
        for _ in range(max_lines):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            if _KNOWN_CAPTION_RE.search(text) or text.startswith("<"):
                break
            values.append(text)
        return tuple(reversed(values))
    return ()


def _value_below_caption(
    lines: list[str], caption_re: re.Pattern[str]
) -> tuple[str, ...]:
    """First content line below the caption: registration-style faces
    print the exact-name caption above its value."""
    for index, line in enumerate(lines):
        if not caption_re.search(line):
            continue
        for below in lines[index + 1 : index + 4]:
            text = below.strip()
            if not text or text.startswith("<"):
                continue
            if _KNOWN_CAPTION_RE.search(text) or set(text) <= set("-_= "):
                break
            return (text,)
        return ()
    return ()


def _cusips_above_caption(lines: list[str]) -> tuple[str, ...]:
    """CUSIPs for the CUSIP caption: same-line prefix first, then the
    value lines above it (one per class), then just below it; a caption
    whose window holds no CUSIP falls through to the next caption."""
    for index, line in enumerate(lines):
        match = _CUSIP_CAPTION_RE.search(line)
        if match is None:
            continue
        own = parse_cusip(line[: match.start()])
        if own is not None:
            return (own,)
        cusips: list[str] = []
        cursor = index
        for _ in range(4):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            cusip = parse_cusip(text)
            if cusip is None:
                break
            cusips.append(cusip)
        if cusips:
            return tuple(reversed(cusips))
        suffix = parse_cusip(line[match.end() :])
        if suffix is not None:
            return (suffix,)
        for below in lines[index + 1 : index + 3]:
            if _KNOWN_CAPTION_RE.search(below):
                break
            cusip = parse_cusip(below)
            if cusip is not None:
                return (cusip,)
    return ()


def analyze_tender_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single tender review case producing kind and cover diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "SC TO")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir,
        record,
        form=resolved_form,
        family="SC TO",
        text=text,
        detect_sections=False,
    )
    if rep is None:
        return None
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family="SC TO")
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""
    cover_lines = lines[start:end] if end > start else lines[:_HEAD_LINES]

    kind = _classify_kind(resolved_form, lines)
    taxonomy = _taxonomy_for(kind, lines, str(record.get("accession", "")))
    body_text = "\n".join(lines[end:]) if end else text
    sequence = detect_section_sequence(
        body_text, family="SC TO", taxonomy_items=taxonomy
    )
    detected = [section.item_identifier for section in sequence.sections]
    if not detected:
        # Recovery pass: a fallback boundary can swallow a short
        # document whole, leaving the body slice empty; the detector
        # then runs over the full text, as the reinfer seam does for
        # checkmarks. Adopted only when the body pass found nothing.
        full = detect_section_sequence(text, family="SC TO", taxonomy_items=taxonomy)
        if full.sections:
            sequence = full
            detected = [section.item_identifier for section in full.sections]
    rep["taxonomy"] = {
        "item_count": len(detected),
        "detected_items": detected,
    }
    rep["anomalies"] = [
        anomaly
        for anomaly in rep["anomalies"]
        if anomaly["kind"] != "no_items_detected"
    ]
    if not detected:
        rep["anomalies"].append(
            anomaly_record(
                "no_items_detected",
                f"no statutory items matched for tender kind {kind.value}",
            )
        )

    head_lines = lines[:120]
    subject = (
        _value_above_caption(cover_lines, _SUBJECT_CAPTION_RE)
        or _value_above_caption(head_lines, _SUBJECT_CAPTION_RE)
        or _value_below_caption(head_lines, _SUBJECT_CAPTION_RE)
    )
    filers = _value_above_caption(
        cover_lines, _FILING_PERSON_CAPTION_RE, max_lines=10
    ) or _value_above_caption(head_lines, _FILING_PERSON_CAPTION_RE, max_lines=10)
    if not filers and subject:
        caption_line = next(
            (line for line in head_lines if _SUBJECT_CAPTION_RE.search(line)),
            "",
        )
        if _COMBINED_FILER_RE.search(caption_line):
            filers = subject
    class_title = _value_above_caption(
        cover_lines, _CLASS_CAPTION_RE, max_lines=2
    ) or _value_above_caption(head_lines, _CLASS_CAPTION_RE, max_lines=2)
    cusips = _cusips_above_caption(cover_lines) or _cusips_above_caption(head_lines)
    head_text = "\n".join(head_lines)
    fields = {
        "kind": kind.value,
        "subject_company": subject[0] if subject else None,
        "filing_persons": filers,
        "class_title": " ".join(class_title) if class_title else None,
        "cusip": cusips[0] if cusips else None,
        "cusips": cusips,
        "notice_contact_present": bool(
            _NOTICE_CAPTION_RE.search(cover_text)
            or _NOTICE_CAPTION_RE.search(head_text)
        ),
        "fee_table_present": bool(
            _FEE_TABLE_RE.search(cover_text) or _FEE_TABLE_RE.search(head_text)
        ),
        "offer_to_purchase_exhibit": bool(_OFFER_TO_PURCHASE_RE.search(text)),
        "letter_of_transmittal_exhibit": bool(_TRANSMITTAL_RE.search(text)),
    }
    rep["form_tender"] = fields

    states = rep["checkmarks"].get("candidate_states", {})
    for key in _DESIGNATION_KEYS + _MARK_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"
    rep["checkmarks"]["designations"] = tuple(
        key for key in _DESIGNATION_KEYS if rep["checkmarks"][key]
    )

    if not fields["subject_company"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_subject_company",
                "no subject company resolved from the cover caption",
            )
        )
    if not fields["filing_persons"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_filing_person",
                "no filing person resolved from the cover caption",
            )
        )
    if not fields["class_title"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_class_title",
                "no class title resolved from the cover caption",
            )
        )
    if not fields["cusip"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_cusip", "no valid CUSIP matched near the cover caption"
            )
        )
    if not fields["notice_contact_present"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_notice_contact",
                "no notice-contact caption matched on the cover",
            )
        )
    return rep


def summarize_tender_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual tender case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="SC TO")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_tender", {})

    kind_counts: dict[str, int] = {}
    for rep in case_reports:
        kind = str(fields_of(rep).get("kind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    summary["form_tender_scorecard"] = {
        "kind_counts": kind_counts,
        "subject_company_count": sum(
            1 for r in case_reports if fields_of(r).get("subject_company")
        ),
        "filing_person_count": sum(
            1 for r in case_reports if fields_of(r).get("filing_persons")
        ),
        "class_title_count": sum(
            1 for r in case_reports if fields_of(r).get("class_title")
        ),
        "cusip_count": sum(1 for r in case_reports if fields_of(r).get("cusip")),
        "notice_contact_count": sum(
            1 for r in case_reports if fields_of(r).get("notice_contact_present")
        ),
        "fee_table_count": sum(
            1 for r in case_reports if fields_of(r).get("fee_table_present")
        ),
        "offer_to_purchase_exhibit_count": sum(
            1 for r in case_reports if fields_of(r).get("offer_to_purchase_exhibit")
        ),
        "letter_of_transmittal_exhibit_count": sum(
            1 for r in case_reports if fields_of(r).get("letter_of_transmittal_exhibit")
        ),
        "designation_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _DESIGNATION_KEYS
        },
        "mark_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _MARK_KEYS
        },
    }
    return summary


analyze_case = analyze_tender_review_case
summarize_cases = summarize_tender_cases

__all__ = [
    "analyze_case",
    "analyze_tender_review_case",
    "summarize_cases",
    "summarize_tender_cases",
]
