"""Statutory narrative subsection parser for Schedule 13D/13G items."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    NarrativeField,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number
from edgar_sec.foundation.regex.builder import build_alternation

_RE_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_RE_SUBSECTION_SPLIT = re.compile(
    r"(?im)(?:^[ \t]*|[;.]\s+)(?:\(?\bITEM\s+\d+\b\s*)?(?:\(([a-f])\)|([a-f])[.:]|\b([a-f])\))[ \t]*(?:[:.-][ \t]*)?"
)
_RE_ROMAN_SPLIT = re.compile(
    r"(?im)(?:^[ \t]*|[;.]\s+)(?:\(c\)\s*)?(?:\(([ivx]+|\d+)\)|([ivx]+|\d+)[.:]|\b([ivx]+|\d+)\))[ \t]*(?:[:.-][ \t]*)?"
)
_SUBSECTION_BOUNDARY_TERMS = (
    r"ITEM\s+\d+\b",
    r"SIGNATURE\b",
    r"</?PAGE>",
    r"PAGE\s+\d+\s+OF\s+\d+",
)
_SUBSECTION_BOUNDARY_ALT = build_alternation(
    _SUBSECTION_BOUNDARY_TERMS, auto_escape=False, compact=True
)
_RE_SUBSECTION_BOUNDARY = re.compile(rf"(?im)^\s*(?:{_SUBSECTION_BOUNDARY_ALT})")

_ISSUER_NAME_LABELS = build_alternation(
    ("NAME OF ISSUER", "ISSUER NAME", "NAME OF THE ISSUER"),
    auto_escape=True,
    compact=True,
)
_ISSUER_ADDRESS_LABELS = build_alternation(
    (
        "ADDRESS OF ISSUER'S PRINCIPAL EXECUTIVE OFFICES",
        "ADDRESS OF ISSUERS PRINCIPAL EXECUTIVE OFFICES",
        "NAME OF ISSUER'S PRINCIPAL EXECUTIVE OFFICES",
        "NAME OF ISSUERS PRINCIPAL EXECUTIVE OFFICES",
        "ADDRESS OF PRINCIPAL EXECUTIVE OFFICES",
        "PRINCIPAL EXECUTIVE OFFICES",
    ),
    auto_escape=True,
    compact=True,
)
_PERSON_NAME_LABELS = build_alternation(
    (
        "NAME OF PERSON FILING",
        "NAMES OF PERSONS FILING",
        "NAME OF REPORTING PERSON",
        "NAMES OF REPORTING PERSONS",
        "PERSON FILING",
        "NAME OF PERSON",
    ),
    auto_escape=True,
    compact=True,
)
_PERSON_ADDRESS_LABELS = build_alternation(
    (
        "ADDRESS OF PRINCIPAL BUSINESS OFFICE OR, IF NONE, RESIDENCE",
        "ADDRESS OF PRINCIPAL BUSINESS OFFICE OR IF NONE RESIDENCE",
        "ADDRESS OF PRINCIPAL BUSINESS OFFICE",
        "PRINCIPAL BUSINESS OFFICE",
        "RESIDENCE ADDRESS",
    ),
    auto_escape=True,
    compact=True,
)
_BUSINESS_LABELS = build_alternation(
    (
        "PRESENT PRINCIPAL OCCUPATION OR EMPLOYMENT",
        "PRINCIPAL OCCUPATION OR EMPLOYMENT",
        "PRINCIPAL OCCUPATION",
        "PRINCIPAL BUSINESS",
    ),
    auto_escape=True,
    compact=True,
)
_CITIZENSHIP_LABELS = build_alternation(
    (
        "CITIZENSHIP OR PLACE OF ORGANIZATION",
        "PLACE OF ORGANIZATION",
        "CITIZENSHIP",
    ),
    auto_escape=True,
    compact=True,
)
_SECURITY_CLASS_LABELS = build_alternation(
    ("TITLE OF CLASS OF SECURITIES", "CLASS OF SECURITIES"),
    auto_escape=True,
    compact=True,
)
_CUSIP_LABELS = build_alternation(
    ("CUSIP NUMBER", "CUSIP NO", "CUSIP"),
    auto_escape=True,
    compact=True,
)
_AMOUNT_OWNED_LABELS = build_alternation(
    (
        "AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON",
        "AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON",
        "AGGREGATE AMOUNT BENEFICIALLY OWNED",
        "AMOUNT BENEFICIALLY OWNED",
    ),
    auto_escape=True,
    compact=True,
)
_PERCENT_CLASS_LABELS = build_alternation(
    (
        "PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW",
        "PERCENT OF CLASS REPRESENTED BY AMOUNT",
        "PERCENT OF CLASS",
    ),
    auto_escape=True,
    compact=True,
)
_POWER_GROUP_LABELS = build_alternation(
    (
        "NUMBER OF SHARES AS TO WHICH SUCH PERSON HAS",
        "NUMBER OF SHARES AS TO WHICH THE PERSON HAS",
        "NUMBER OF SHARES BENEFICIALLY OWNED BY EACH",
        "NUMBER OF SHARES BENEFICIALLY OWNED",
        "DEEMED VOTING POWER AND DISPOSITION POWER",
        "NUMBER OF SHARES",
    ),
    auto_escape=True,
    compact=True,
)
_SOLE_VOTING_LABELS = build_alternation(
    (
        "SOLE POWER TO VOTE OR TO DIRECT THE VOTE",
        "SOLE POWER TO VOTE OR DIRECT THE VOTE",
        "SOLE POWER TO VOTE",
    ),
    auto_escape=True,
    compact=True,
)
_SHARED_VOTING_LABELS = build_alternation(
    (
        "SHARED POWER TO VOTE OR TO DIRECT THE VOTE",
        "SHARED POWER TO VOTE OR DIRECT THE VOTE",
        "SHARED POWER TO VOTE",
    ),
    auto_escape=True,
    compact=True,
)
_SOLE_DISPOSITIVE_LABELS = build_alternation(
    (
        "SOLE POWER TO DISPOSE OR TO DIRECT THE DISPOSITION OF",
        "SOLE POWER TO DISPOSE OR DIRECT THE DISPOSITION OF",
        "SOLE POWER TO DISPOSE",
    ),
    auto_escape=True,
    compact=True,
)
_SHARED_DISPOSITIVE_LABELS = build_alternation(
    (
        "SHARED POWER TO DISPOSE OR TO DIRECT THE DISPOSITION OF",
        "SHARED POWER TO DISPOSE OR DIRECT THE DISPOSITION OF",
        "SHARED POWER TO DISPOSE",
    ),
    auto_escape=True,
    compact=True,
)

_LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "issuerName": re.compile(rf"(?i)^\s*(?:{_ISSUER_NAME_LABELS})\s*[:.-]?\s*"),
    "issuerAddress": re.compile(rf"(?i)^\s*(?:{_ISSUER_ADDRESS_LABELS})\s*[:.-]?\s*"),
    "filingPersonName": re.compile(rf"(?i)^\s*(?:{_PERSON_NAME_LABELS})\s*[:.-]?\s*"),
    "principalBusinessAddress": re.compile(
        rf"(?i)^\s*(?:{_PERSON_ADDRESS_LABELS})\s*[:.-]?\s*"
    ),
    "principalBusiness": re.compile(rf"(?i)^\s*(?:{_BUSINESS_LABELS})\s*[:.-]?\s*"),
    "citizenshipOrOrganization": re.compile(
        rf"(?i)^\s*(?:{_CITIZENSHIP_LABELS})\s*[:.-]?\s*"
    ),
    "securitiesClassTitle": re.compile(
        rf"(?i)^\s*(?:{_SECURITY_CLASS_LABELS})\s*[:.-]?\s*"
    ),
    "cusip": re.compile(rf"(?i)^\s*(?:{_CUSIP_LABELS})\s*[:.-]?\s*"),
    "aggregateAmountOwned": re.compile(
        rf"(?i)^\s*(?:{_AMOUNT_OWNED_LABELS})\s*[:.-]?\s*"
    ),
    "percentOfClass": re.compile(rf"(?i)^\s*(?:{_PERCENT_CLASS_LABELS})\s*[:.-]?\s*"),
    "votingAndDispositivePowers": re.compile(
        rf"(?i)^\s*(?:{_POWER_GROUP_LABELS})\s*[:.-]?\s*"
    ),
    "soleVotingPower": re.compile(rf"(?i)^\s*(?:{_SOLE_VOTING_LABELS})\s*[:.-]?\s*"),
    "sharedVotingPower": re.compile(
        rf"(?i)^\s*(?:{_SHARED_VOTING_LABELS})\s*[:.-]?\s*"
    ),
    "soleDispositivePower": re.compile(
        rf"(?i)^\s*(?:{_SOLE_DISPOSITIVE_LABELS})\s*[:.-]?\s*"
    ),
    "sharedDispositivePower": re.compile(
        rf"(?i)^\s*(?:{_SHARED_DISPOSITIVE_LABELS})\s*[:.-]?\s*"
    ),
}

_SUBSECTION_FIELD_MAP_13G: dict[int, dict[str, str]] = {
    1: {
        "a": "issuerName",
        "b": "issuerAddress",
    },
    2: {
        "a": "filingPersonName",
        "b": "principalBusinessAddress",
        "c": "citizenshipOrOrganization",
        "d": "securitiesClassTitle",
        "e": "cusip",
    },
    4: {
        "a": "aggregateAmountOwned",
        "b": "percentOfClass",
        "c": "votingAndDispositivePowers",
    },
}

_ROMAN_FIELD_MAP: dict[str, str] = {
    "i": "soleVotingPower",
    "1": "soleVotingPower",
    "ii": "sharedVotingPower",
    "2": "sharedVotingPower",
    "iii": "soleDispositivePower",
    "3": "soleDispositivePower",
    "iv": "sharedDispositivePower",
    "4": "sharedDispositivePower",
}

_SUBSECTION_FIELD_MAP_13D: dict[int, dict[str, str]] = {
    1: {
        "a": "securitiesClassTitle",
        "b": "issuerName",
    },
    2: {
        "a": "filingPersonName",
        "b": "principalBusinessAddress",
        "c": "principalBusiness",
        "f": "citizenshipOrOrganization",
    },
    5: {
        "a": "percentageOfClassSecurities",
        "b": "numberOfShares",
        "c": "transactionDesc",
        "d": "listOfShareholders",
        "e": "date5PercentOwnership",
    },
}

_INVALID_NAME_STARTS = build_alternation(
    ("amount", "percent", "number of shares", "check", "item"),
    auto_escape=True,
    compact=True,
)
_RE_INVALID_NAME = re.compile(rf"(?i)^\s*(?:{_INVALID_NAME_STARTS}|\d+)\b")
_NUMERIC_FIELD_TAGS = {
    "aggregateAmountOwned",
    "soleVotingPower",
    "sharedVotingPower",
    "soleDispositivePower",
    "sharedDispositivePower",
}

_ZERO_OWNERSHIP_ALT = build_alternation(
    (
        r"beneficially\s+owns?\s+no",
        r"owns?\s+0\s+shares",
        r"ceased\s+to\s+be(?:\s+a)?\s+(?:beneficial\s+owner|record\s+holder)",
        r"not\s+applicable",
        r"none",
    ),
    auto_escape=False,
)
_RE_ZERO_OWNERSHIP = re.compile(rf"(?i)\b(?:{_ZERO_OWNERSHIP_ALT})\b")

_SHARE_PREFIX_ALT = build_alternation(
    (
        r"aggregate(?:\s+number|\s+amount)?(?:\s+of\s+(?:securities|shares))?",
        r"beneficially\s+own[s]?",
        r"ownership\s+of",
        r"held\s+by",
    ),
    auto_escape=False,
)
_SHARE_UNIT_ALT = build_alternation(
    (
        "shares of common stock",
        "common shares",
        "ordinary shares",
        "shares",
        "units",
        "common stock",
    ),
    auto_escape=True,
)
_CONNECTOR_ALT = build_alternation(
    (r"an\s+aggregate\s+of\s+", r"of\s+", r"[:.-]\s*"),
    auto_escape=False,
)
_RE_SHARE_COUNT = re.compile(
    rf"(?i)(?:(?:{_SHARE_PREFIX_ALT})\s*(?:{_CONNECTOR_ALT})?|^|\b)"
    rf"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:{_SHARE_UNIT_ALT})\b"
)

_PERCENT_PREFIX_ALT = build_alternation(
    (
        r"percentage(?:\s+of\s+class)?\s*[:.-]?",
        r"representing(?:\s+approximately)?",
        r"approximate\s+percentage",
        r"percent\s+of\s+class\s*[:.-]?",
    ),
    auto_escape=False,
)
_PERCENT_SIGN_ALT = build_alternation(
    ("%", r"percent\b"),
    auto_escape=False,
)
_RE_PERCENT_OF_CLASS = re.compile(
    rf"(?i)(?:(?:{_PERCENT_PREFIX_ALT})\s*|^|\b)([0-9]+(?:\.[0-9]+)?)\s*(?:{_PERCENT_SIGN_ALT})"
)

_CHECKED_BOX_ALT = build_alternation(
    (
        r"\[\s*[xX✓*]\s*\]",
        r"_\s*[xX✓*]\s*_",
        r"\(\s*[xX✓*]\s*\)",
    ),
    auto_escape=False,
)
_CHECKED_BOX = rf"(?:{_CHECKED_BOX_ALT})"
_RE_CHECKED_SUBPART_POST = re.compile(
    rf"(?i)(?:\(?\s*([a-k])\s*\)|([a-k])\.)\s*{_CHECKED_BOX}"
)
_RE_CHECKED_SUBPART_PRE = re.compile(
    rf"(?i){_CHECKED_BOX}\s*(?:\(?\s*([a-k])\s*\)|([a-k])\.)"
)
_RE_ITEM5_13G_CESSATION = re.compile(
    rf"(?is)ceased\s+to\s+be.*{_CHECKED_BOX}|{_CHECKED_BOX}.*ceased\s+to\s+be"
)
_ITEM3_CLASSIFICATION_MAP: dict[str, str] = {
    "a": "BD",
    "b": "BK",
    "c": "IC",
    "d": "IV",
    "e": "IA",
    "f": "EP",
    "g": "HC",
    "h": "SA",
    "i": "CP",
    "j": "FI",
    "k": "OO",
}

_BK_TERMS_ALT = build_alternation(
    ("bank loan", "borrowed funds", "credit facility"),
    auto_escape=True,
)
_RE_WC = re.compile(r"(?i)\bworking\s+capital\b")
_RE_PF = re.compile(r"(?i)\bpersonal\s+funds\b")
_RE_BK = re.compile(rf"(?i)\b(?:{_BK_TERMS_ALT})\b")
_RE_AF = re.compile(r"(?i)\baffiliate\s+funds\b")
_RE_OO = re.compile(r"(?i)\bother\s+funds\b")

_CERTIFICATION_PREFIX = build_alternation(
    ("certifications", "certification", "certify"),
    auto_escape=True,
)
_RE_CERTIFICATION_HEADER = re.compile(
    rf"(?i)^\s*(?:item\s+10\s*[:.-]?\s*)?(?:{_CERTIFICATION_PREFIX})\s*[:.-]?\s*"
)


def extract_prose_ownership(text: str) -> tuple[str | None, str | None]:
    """Extracts aggregate share count and class percent from prose text."""
    clean_text = _RE_HTML_TAG.sub(" ", text).strip()
    if _RE_ZERO_OWNERSHIP.search(clean_text[:500]):
        return "0", "0"
    shares: str | None = None
    pct: str | None = None
    m_s = _RE_SHARE_COUNT.search(clean_text)
    if m_s:
        shares = normalize_schema_number(
            m_s.group(1),
            integer=True,
            strip_units=True,
            strip_footnotes=True,
            extract_leading_number=True,
        )
    m_p = _RE_PERCENT_OF_CLASS.search(clean_text)
    if m_p:
        pct = normalize_schema_number(
            m_p.group(1),
            integer=False,
            strip_percent=True,
            strip_footnotes=True,
            extract_leading_number=True,
        )
    return shares, pct


def extract_item3_classification_codes(text: str) -> str | None:
    """Extracts SEC 2-character filer type codes from Schedule 13G Item 3."""
    codes: list[str] = []
    seen: set[str] = set()
    for m in _RE_CHECKED_SUBPART_POST.finditer(text):
        letter = (m.group(1) or m.group(2)).lower()
        code = _ITEM3_CLASSIFICATION_MAP.get(letter)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    for m in _RE_CHECKED_SUBPART_PRE.finditer(text):
        letter = (m.group(1) or m.group(2)).lower()
        code = _ITEM3_CLASSIFICATION_MAP.get(letter)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return ", ".join(codes) if codes else None


def extract_item3_fund_codes(text: str) -> str | None:
    """Extracts SEC 2-character source-of-funds codes from Schedule 13D Item 3."""
    codes: list[str] = []
    if _RE_WC.search(text):
        codes.append("WC")
    if _RE_PF.search(text):
        codes.append("PF")
    if _RE_BK.search(text):
        codes.append("BK")
    if _RE_AF.search(text):
        codes.append("AF")
    if _RE_OO.search(text):
        codes.append("OO")
    return ", ".join(codes) if codes else None


def clean_subsection_value(tag: str, raw_value: str) -> str:
    """Strips leading statutory labels, HTML tags, and padding from a subsection value."""
    text = _RE_HTML_TAG.sub(" ", raw_value).strip()
    label_pattern = _LABEL_PATTERNS.get(tag)
    if label_pattern is not None:
        text = label_pattern.sub("", text).strip()
    if tag in {"issuerName", "filingPersonName"} and _RE_INVALID_NAME.match(text):
        return ""
    if tag in _NUMERIC_FIELD_TAGS:
        if text.strip().lower() in {"-", "none", "nil", "n/a", "not applicable", "-0-"}:
            return "0"
        norm = normalize_schema_number(
            text,
            integer=True,
            strip_units=True,
            strip_footnotes=True,
            extract_leading_number=True,
        )
        return norm if norm is not None else ""
    elif tag == "percentOfClass":
        if text.strip().lower() in {"-", "none", "nil", "n/a", "not applicable", "-0-"}:
            return "0"
        norm = normalize_schema_number(
            text,
            integer=False,
            strip_percent=True,
            strip_footnotes=True,
            extract_leading_number=True,
        )
        return norm if norm is not None else ""
    return text


def extract_subsections(
    item_number: int,
    item_text: str,
    family: str = "13G",
    *,
    base_offset: int = 0,
) -> tuple[NarrativeField, ...]:
    """Extracts structured subsections from a statutory narrative item."""
    if not item_text.strip():
        return ()

    if item_number == 3:
        if family == "13G":
            type_code = extract_item3_classification_codes(item_text)
            if type_code:
                return (
                    NarrativeField(
                        tag="typeOfReportingPerson",
                        value=type_code,
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    ),
                )
        else:
            fund_code = extract_item3_fund_codes(item_text)
            if fund_code:
                return (
                    NarrativeField(
                        tag="fundType",
                        value=fund_code,
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    ),
                )

    if item_number == 5:
        if family == "13G":
            if _RE_ITEM5_13G_CESSATION.search(item_text) or _RE_ZERO_OWNERSHIP.search(
                item_text
            ):
                return (
                    NarrativeField(
                        tag="is5PercentCessation",
                        value="Y",
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    ),
                    NarrativeField(
                        tag="aggregateAmountOwned",
                        value="0",
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    ),
                    NarrativeField(
                        tag="percentOfClass",
                        value="0",
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    ),
                )
        elif family == "13D" and _RE_ZERO_OWNERSHIP.search(item_text):
            return (
                NarrativeField(
                    tag="aggregateAmountOwned",
                    value="0",
                    start_offset=base_offset,
                    end_offset=base_offset + len(item_text),
                    source_text=item_text,
                ),
                NarrativeField(
                    tag="percentOfClass",
                    value="0",
                    start_offset=base_offset,
                    end_offset=base_offset + len(item_text),
                    source_text=item_text,
                ),
            )

    if item_number == 10 and family == "13G":
        clean_cert = _RE_HTML_TAG.sub(" ", item_text).strip()
        clean_cert = _RE_CERTIFICATION_HEADER.sub("", clean_cert).strip()
        if clean_cert:
            return (
                NarrativeField(
                    tag="certifications",
                    value=clean_cert,
                    start_offset=base_offset,
                    end_offset=base_offset + len(item_text),
                    source_text=item_text,
                ),
            )

    field_map_registry = (
        _SUBSECTION_FIELD_MAP_13G if family == "13G" else _SUBSECTION_FIELD_MAP_13D
    )
    field_map = field_map_registry.get(item_number)

    matches = list(_RE_SUBSECTION_SPLIT.finditer(item_text))
    if not matches:
        if (family == "13D" and item_number == 5) or (
            family == "13G" and item_number == 4
        ):
            shares, pct = extract_prose_ownership(item_text)
            p_fields: list[NarrativeField] = []
            if shares:
                p_fields.append(
                    NarrativeField(
                        tag="aggregateAmountOwned",
                        value=shares,
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    )
                )
            if pct:
                p_fields.append(
                    NarrativeField(
                        tag="percentOfClass",
                        value=pct,
                        start_offset=base_offset,
                        end_offset=base_offset + len(item_text),
                        source_text=item_text,
                    )
                )
            return tuple(p_fields)
        return ()

    if not field_map:
        return ()

    fields: list[NarrativeField] = []
    if matches and matches[0].start() > 0 and field_map.get("a"):
        lead_letter = next(
            (g for g in matches[0].groups() if g is not None), ""
        ).lower()
        if lead_letter in {"b", "2"}:
            lead_val = item_text[: matches[0].start()].strip()
            lead_clean = clean_subsection_value(field_map["a"], lead_val)
            if lead_clean:
                fields.append(
                    NarrativeField(
                        tag=field_map["a"],
                        value=lead_clean,
                        start_offset=base_offset,
                        end_offset=base_offset + matches[0].start(),
                        source_text=lead_val,
                    )
                )

    for idx, match in enumerate(matches):
        letter = next((g for g in match.groups() if g is not None), "").lower()
        tag = field_map.get(letter)
        if tag is None:
            continue
        val_start = match.end()
        val_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(item_text)
        raw_val = item_text[val_start:val_end]
        if b_match := _RE_SUBSECTION_BOUNDARY.search(raw_val):
            val_end = val_start + b_match.start()
            raw_val = item_text[val_start:val_end]

        if tag == "votingAndDispositivePowers":
            sub_matches = list(_RE_ROMAN_SPLIT.finditer(raw_val))
            if sub_matches:
                for s_idx, sm in enumerate(sub_matches):
                    s_key = next((g for g in sm.groups() if g is not None), "").lower()
                    s_tag = _ROMAN_FIELD_MAP.get(s_key)
                    if s_tag is None:
                        continue
                    s_start = val_start + sm.end()
                    s_end = (
                        val_start + sub_matches[s_idx + 1].start()
                        if s_idx + 1 < len(sub_matches)
                        else val_end
                    )
                    s_raw = item_text[s_start:s_end]
                    if sb_match := _RE_SUBSECTION_BOUNDARY.search(s_raw):
                        s_end = s_start + sb_match.start()
                        s_raw = item_text[s_start:s_end]
                    s_clean = clean_subsection_value(s_tag, s_raw)
                    if not s_clean:
                        continue
                    s_trailing = len(s_raw) - len(s_raw.rstrip())
                    s_field_start = base_offset + val_start + sm.start()
                    s_field_end = base_offset + s_end - s_trailing
                    fields.append(
                        NarrativeField(
                            tag=s_tag,
                            value=s_clean,
                            start_offset=s_field_start,
                            end_offset=s_field_end,
                            source_text=item_text[
                                val_start + sm.start() : s_end - s_trailing
                            ],
                        )
                    )
                continue

        cleaned_val = clean_subsection_value(tag, raw_val)
        if not cleaned_val:
            continue
        trailing = len(raw_val) - len(raw_val.rstrip())
        start_offset = base_offset + match.start()
        end_offset = base_offset + val_end - trailing
        source_excerpt = item_text[match.start() : val_end - trailing]
        fields.append(
            NarrativeField(
                tag=tag,
                value=cleaned_val,
                start_offset=start_offset,
                end_offset=end_offset,
                source_text=source_excerpt,
            )
        )

        if (
            family == "13D"
            and item_number == 5
            and tag == "percentageOfClassSecurities"
        ):
            shares, pct = extract_prose_ownership(raw_val)
            if shares:
                fields.append(
                    NarrativeField(
                        tag="aggregateAmountOwned",
                        value=shares,
                        start_offset=base_offset + val_start,
                        end_offset=base_offset + val_end,
                        source_text=raw_val,
                    )
                )
            if pct:
                fields.append(
                    NarrativeField(
                        tag="percentOfClass",
                        value=pct,
                        start_offset=base_offset + val_start,
                        end_offset=base_offset + val_end,
                        source_text=raw_val,
                    )
                )

    return tuple(fields)


__all__ = [
    "clean_subsection_value",
    "extract_item3_classification_codes",
    "extract_item3_fund_codes",
    "extract_prose_ownership",
    "extract_subsections",
]
