"""Extracts issuer and notice metadata from the cover header slice."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.beneficial_ownership.identifiers import (
    CUSIP_UNAVAILABLE_POLICY,
)
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    IssuerMetadata,
)
from edgar_sec.engine.forms.common.entities import ORGANIZATION_SUFFIX_RE
from edgar_sec.engine.forms.common.tables import parse_address_parts
from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    cusip_page_residue_match,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import SEC_DATE_FORMATS, parse_date

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "issuer_name": (
        "name of issuer",
        "name of subject company (issuer)",
        "name of subject company",
        "subject company",
        "issuer name",
        "name of company",
        "company name",
    ),
    "issuer_cik": ("cik of issuer", "issuer cik", "cik number of issuer"),
    "issuer_address": ("address of issuer", "issuer address"),
    "security_class": (
        "title of class of securities",
        "title of class",
        "class of securities",
    ),
    "cusip": (
        "cusip number of class of securities",
        "cusip number",
        "cusip no.",
        "cusip",
    ),
    "event_date": (
        "date of event which requires filing of this statement",
        "date of event requiring filing of this statement",
        "date of event which requires filing",
        "date of event",
        "event date",
    ),
    "notice_contact": (
        "name of person authorized to receive notices and communications",
        "name, address and telephone number of person authorized to receive notices and communications",
        "name and address of person authorized to receive notices and communications",
        "person authorized to receive notices and communications",
    ),
    "notice_phone": (
        "telephone number of person authorized to receive notices and communications",
        "telephone number",
        "phone number",
    ),
    "notice_address": (
        "address of person authorized to receive notices and communications",
        "address of person authorized to receive notices",
    ),
}
_ALL_LABELS = tuple(
    sorted(
        (label for labels in _FIELD_LABELS.values() for label in labels),
        key=len,
        reverse=True,
    )
)
_LABEL_ALT = build_alternation(_ALL_LABELS, auto_escape=True)
_PAREN_LABEL_RE = re.compile(rf"(?i)\(\s*(?P<label>{_LABEL_ALT})\s*\.?\s*\)")
_PHONE_ALT = build_alternation(
    (
        r"\+\d{1,3}\s+(?:\d{2,4}\s+){1,2}\d{2,4}",
        r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{1,4}\)?[\s.-]?)?\d{3,4}[\s.-]\d{4}",
    ),
    auto_escape=False,
    compact=False,
)
_PHONE_RE = re.compile(rf"(?<!\d)(?:{_PHONE_ALT})(?!\d)")
_WHITESPACE_RE = re.compile(r"\s+")
_TABLE_MARKUP_RE = re.compile(r"(?i)^\s*</?TABLE>\s*$")
_ATTENTION_RE = re.compile(r"(?i)^\s*ATTENTION\s*:\s*(?P<name>.+?)\s*$")
_COPY_TO_RE = re.compile(r"(?i)^\s*(?:WITH\s+)?COPY\s+TO\s*:?\s*$")
_CUSIP_TOKEN_RE = re.compile(r"(?i)(?<![0-9A-Z])[0-9A-Z*@#]{9}(?![0-9A-Z])")
_PHONE_LABEL_ALT = build_alternation(
    ("TEL", "TELEPHONE", "PHONE"), auto_escape=True, compact=True
)
_RE_PHONE_LABEL = re.compile(rf"(?i)\b(?:{_PHONE_LABEL_ALT})\.?\s*(?:NO\.?)?:?\s*$")
_ADDRESS_START_ALT = build_alternation(
    (r"\d{1,5}\s+[A-Z]", r"P\.?\s*O\.?\s+BOX\b", r"LEVEL\s+\d+\b"),
    compact=False,
)
_RE_ADDRESS_START = re.compile(rf"(?i)(?<![A-Z0-9])(?:{_ADDRESS_START_ALT})")
_RE_SUITE_CITY = re.compile(
    r"(?i)^\s*(?P<suite>SUITE\s+\w+)\s+(?P<city>[A-Z][A-Z .'-]*)\s*$"
)
_INVALID_ISSUER_TERMS = build_alternation(
    (
        r"has\b",
        r"is\b",
        r"are\b",
        r"was\b",
        r"were\b",
        r"shall\b",
        r"will\b",
        r"the\s+principal",
        r"principal\s+executive",
        r"title\s+of\s+class",
        r"\(\s*title\s+of\s+class",
        r"<\s*table",
        r"---+",
        r"\(?\s*amendment\b",
        r"pursuant\s+to\b",
        r"240\.13d",
        r"\(?\s*name\s+of\b",
        r"[\*†‡]+",
    ),
    auto_escape=False,
    compact=False,
)
_RE_INVALID_ISSUER_NAME = re.compile(rf"(?i)^\s*(?:{_INVALID_ISSUER_TERMS})")
_RE_AMENDMENT = re.compile(r"(?i)\bamendment\b")
_RE_PUNCT_ONLY = re.compile(r"^[\s*†‡.\-_=()]+$")
_SEC_HEADER_TERMS = build_alternation(
    (
        r"securities\s+and\s+exchange",
        r"washington",
        r"schedule\s+13[dg]",
        r"under\s+the",
        r"amendment\s+no",
        r"\(date\s+of\)",
    ),
    auto_escape=False,
    compact=True,
)
_RE_SEC_HEADER = re.compile(rf"(?i)\b(?:{_SEC_HEADER_TERMS})\b")
_RE_FMR_HEADER = re.compile(
    r"(?i)amendment\s+no\.?\s*\d+\s+(?P<issuer>.+?)\s+(?P<class>common\s+stock|ordinary\s+shares|preferred\s+stock|class\s+[a-z0-9]+)\s+cusip\s*#?\s*(?P<cusip>[0-9a-z]{8,9})"
)
_INLINE_ISSUER_DELIM_ALT = build_alternation(
    (r"_{2,}", r"\s{2,}", r"\bitem\b", r"\n", r"$"),
    auto_escape=False,
)
_RE_INLINE_ISSUER = re.compile(
    rf"(?i)\bname\s+of\s+(?:issuer|company)\s*[:.-]\s*(?P<name>[^_\n\r]{{3,60}}?)(?:{_INLINE_ISSUER_DELIM_ALT})"
)
_SAME_LINE_ISSUER_SUFFIX_ALT = build_alternation(
    (r"common\s+stock", r"ordinary\s+shares", r"class\s+[a-z0-9]+", r"cusip\b"),
    auto_escape=False,
)
_RE_SAME_LINE_ISSUER = re.compile(
    rf"(?i)^(?P<cand>[^_\n\r]{{3,60}}?)\s+(?:{_SAME_LINE_ISSUER_SUFFIX_ALT})"
)
_LABEL_CONTINUATIONS = frozenset(
    {
        "and",
        "authorized",
        "communications",
        "for",
        "from",
        "no",
        "number",
        "of",
        "the",
        "this",
        "to",
        "which",
        "who",
        "with",
    }
)
_RE_NAME_OF_ISSUER_PAREN = re.compile(r"(?i)\(\s*name\s+of\s+issuer\s*\)")
_RE_PAREN_QUALIFIER = re.compile(r"\(.*?\)")


def _label_and_value(line: str) -> tuple[str, str] | None:
    original = line.strip()
    if original.startswith("(") and original.endswith(")"):
        inner = original[1:-1].strip()
        norm_inner = " ".join(inner.lower().split())
        if norm_inner in _ALL_LABELS:
            return norm_inner, ""
        clean_inner = " ".join(_RE_PAREN_QUALIFIER.sub("", inner).lower().split())
        if clean_inner in _ALL_LABELS:
            return clean_inner, ""
        return None
    normalized = " ".join(original.lower().split())
    for label in _ALL_LABELS:
        if normalized == label:
            return label, ""
        if normalized.startswith(label) and len(normalized) > len(label):
            boundary = normalized[len(label)]
            tail = normalized[len(label) :].lstrip()
            if boundary in ":.-|" or (
                boundary.isspace()
                and tail.split(maxsplit=1)[0] not in _LABEL_CONTINUATIONS
                and not original.startswith("(")
            ):
                value_start = original.lower().find(label) + len(label)
                return label, original[value_start:].lstrip(" \t:.-|)")
    if original.startswith("(") and ")" in original:
        close_paren = original.find(")")
        label_part = " ".join(original[1:close_paren].lower().split())
        if label_part in _ALL_LABELS:
            return label_part, original[close_paren + 1 :].strip(" \t:.-|")
    return None


def _is_plausible_value(field: str, val: str) -> bool:
    v = val.strip(" _=-")
    if not v or _RE_PUNCT_ONLY.fullmatch(v):
        return False
    if field == "issuer_name":
        return (
            not _RE_INVALID_ISSUER_NAME.search(v)
            and not _RE_SEC_HEADER.search(v)
            and parse_date(v.strip("() ")) is None
            and not bool(_CUSIP_TOKEN_RE.fullmatch(v.replace(" ", "")))
            and len(v) >= 3
        )
    if field == "cusip":
        return bool(
            _CUSIP_TOKEN_RE.search(v) or _CUSIP_TOKEN_RE.search(v.replace(" ", ""))
        )
    if field == "event_date":
        return parse_date(v) is not None
    if field == "security_class":
        return (
            not _RE_SEC_HEADER.search(v)
            and not _RE_INVALID_ISSUER_NAME.search(v)
            and len(v) >= 3
        )
    return True


def _label_sequence(
    lines: list[str], start: int
) -> tuple[tuple[str, str], int, bool] | None:
    direct = _label_and_value(lines[start])
    parenthesized = lines[start].strip().startswith("(")
    if direct is not None:
        return direct, start + 1, parenthesized

    parts = [lines[start].strip()]
    for index in range(start + 1, min(start + 4, len(lines))):
        if lines[index].strip():
            parts.append(lines[index].strip())
        matched = _label_and_value(" ".join(parts))
        if matched is not None:
            return matched, index + 1, parenthesized
    return None


def extract_issuer_metadata(text: str) -> IssuerMetadata:
    """Extracts issuer identity, CUSIP, date, and notice contact metadata."""
    lines = text.splitlines()
    values: dict[str, list[str]] = {field: [] for field in _FIELD_LABELS}
    label_fields = {
        label: field for field, labels in _FIELD_LABELS.items() for label in labels
    }
    labels_below = False
    for idx, l in enumerate(lines[:30]):
        if _RE_NAME_OF_ISSUER_PAREN.search(l):
            prev = idx - 1
            while prev >= 0 and (
                not lines[prev].strip()
                or set(lines[prev].strip()) <= {"-", "_", "=", " "}
            ):
                prev -= 1
            if prev >= 0:
                prev_text = lines[prev].strip()
                if _RE_SEC_HEADER.search(prev_text) or _RE_AMENDMENT.search(prev_text):
                    prev2 = prev - 1
                    while prev2 >= 0 and not lines[prev2].strip():
                        prev2 -= 1
                    if (
                        prev2 < 0
                        or _RE_SEC_HEADER.search(lines[prev2])
                        or _RE_AMENDMENT.search(lines[prev2])
                    ):
                        labels_below = True
            break
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        label_match = _label_sequence(lines, index)
        if label_match is None:
            index += 1
            continue
        (label, value), label_end, parenthesized = label_match
        field = label_fields[label]
        next_value_index = label_end
        inline_phone = _phone_match(value) if field == "notice_contact" else None
        if parenthesized and inline_phone is not None:
            values["notice_phone"].append(inline_phone.group(0))
            value = ""
        if not value and parenthesized and field == "notice_contact":
            prior_label = -1
            for candidate_index in range(index - 1, -1, -1):
                candidate = lines[candidate_index].strip()
                match = _PAREN_LABEL_RE.search(candidate)
                if match is None:
                    continue
                prior_field = label_fields.get(
                    " ".join(match.group("label").lower().split())
                )
                if prior_field in {
                    "issuer_name",
                    "issuer_address",
                    "security_class",
                    "cusip",
                    "event_date",
                }:
                    prior_label = candidate_index
                    break
            block = [
                _clean_scalar(line)
                for line in lines[prior_label + 1 : index]
                if _clean_scalar(line) and not _TABLE_MARKUP_RE.fullmatch(line)
            ]
            if block:
                value = block[0]
                phone_index = next(
                    (
                        position
                        for position, line in enumerate(block)
                        if _phone_match(line) is not None
                    ),
                    None,
                )
                if phone_index is not None:
                    phone = _phone_match(block[phone_index])
                    values["notice_phone"].append(phone.group(0))
                attention = next(
                    (
                        (position, _ATTENTION_RE.fullmatch(line))
                        for position, line in enumerate(block)
                        if _ATTENTION_RE.fullmatch(line) is not None
                    ),
                    None,
                )
                copy_to_index = next(
                    (
                        position
                        for position, line in enumerate(block)
                        if _COPY_TO_RE.fullmatch(line)
                    ),
                    None,
                )
                address_end = min(
                    (
                        position
                        for position in (
                            phone_index,
                            attention[0] if attention is not None else None,
                            copy_to_index,
                        )
                        if position is not None
                    ),
                    default=len(block),
                )
                address_lines = block[1:address_end]
                if attention is not None and attention[1] is not None:
                    value = attention[1].group("name").strip()
                if phone_index == 0:
                    phone = _phone_match(block[0])
                    prefix = _RE_PHONE_LABEL.sub("", block[0][: phone.start()]).strip(
                        " ,\t"
                    )
                    address_start = _RE_ADDRESS_START.search(prefix)
                    if address_start is not None:
                        value = prefix[: address_start.start()].strip(" ,\t")
                        address_lines = [prefix[address_start.start() :].strip(" ,\t")]
                    else:
                        value = prefix
                if address_lines:
                    values["notice_address"].append("\n".join(address_lines))
        if (
            not value
            and parenthesized
            and field in {"issuer_name", "security_class", "cusip", "event_date"}
        ):
            if not labels_below:
                previous_index = index - 1
                while previous_index >= 0 and (
                    not lines[previous_index].strip()
                    or set(lines[previous_index].strip()) <= {"-", "_", "=", " "}
                    or _TABLE_MARKUP_RE.fullmatch(lines[previous_index].strip())
                    or (
                        field == "issuer_name"
                        and _RE_AMENDMENT.search(lines[previous_index])
                    )
                ):
                    previous_index -= 1
                if (
                    previous_index >= 0
                    and _label_sequence(lines, previous_index) is None
                ):
                    cand = lines[previous_index].strip()
                    if _is_plausible_value(field, cand):
                        value = cand
            if not value:
                for candidate_index in range(label_end, min(label_end + 3, len(lines))):
                    next_line = lines[candidate_index]
                    if not next_line.strip() or _TABLE_MARKUP_RE.fullmatch(
                        next_line.strip()
                    ):
                        continue
                    if _label_sequence(lines, candidate_index) is not None:
                        break
                    cand = next_line.strip()
                    if _is_plausible_value(field, cand):
                        value = cand
                        next_value_index = candidate_index + 1
                    break
        if field in {"issuer_address", "notice_address"}:
            address_lines = [value] if value else []
            for next_line in lines[next_value_index:]:
                if not next_line.strip() or _label_and_value(next_line) is not None:
                    break
                address_lines.append(next_line.strip())
            value = "\n".join(address_lines)
        if value:
            values[field].append(
                value.strip()
                if field in {"issuer_address", "notice_address"}
                else _clean_scalar(value)
            )
        index = max(index + 1, label_end)

    for index, line in enumerate(lines):
        for match in _PAREN_LABEL_RE.finditer(line):
            label = " ".join(match.group("label").lower().split())
            field = label_fields.get(label)
            if field is None:
                continue
            previous_close = line.rfind(")", 0, match.start())
            before_val = _clean_scalar(line[previous_close + 1 : match.start()])
            tail = line[match.end() :]
            next_open = tail.find("(") if "(" in tail else len(tail)
            after_val = _clean_scalar(tail[:next_open])
            if _is_plausible_value(field, before_val):
                value = before_val
            elif _is_plausible_value(field, after_val):
                value = after_val
            else:
                value = ""
            if not value and field == "issuer_name":
                first_open = line.find("(", 0, match.start())
                if first_open > 0:
                    cand = _clean_scalar(line[:first_open])
                    if _is_plausible_value("issuer_name", cand):
                        value = cand
            phone = (
                _phone_match(line[: match.start()])
                if field == "notice_contact"
                else None
            )
            if phone is not None:
                prior_label = -1
                for candidate_index in range(index - 1, -1, -1):
                    candidate_match = _PAREN_LABEL_RE.search(lines[candidate_index])
                    if candidate_match is None:
                        continue
                    prior_field = label_fields.get(
                        " ".join(candidate_match.group("label").lower().split())
                    )
                    if prior_field in {
                        "issuer_name",
                        "issuer_address",
                        "security_class",
                        "cusip",
                        "event_date",
                    }:
                        prior_label = candidate_index
                        break
                block = [
                    _clean_scalar(candidate)
                    for candidate in lines[prior_label + 1 : index]
                    if _clean_scalar(candidate)
                    and not _TABLE_MARKUP_RE.fullmatch(candidate)
                ]
                attention = next(
                    (
                        (position, _ATTENTION_RE.fullmatch(candidate))
                        for position, candidate in enumerate(block)
                        if _ATTENTION_RE.fullmatch(candidate) is not None
                    ),
                    None,
                )
                copy_to_index = next(
                    (
                        position
                        for position, candidate in enumerate(block)
                        if _COPY_TO_RE.fullmatch(candidate)
                    ),
                    None,
                )
                if block:
                    values["notice_contact"].append(
                        attention[1].group("name").strip()
                        if attention is not None and attention[1] is not None
                        else block[0]
                    )
                    address_end = min(
                        (
                            position
                            for position in (
                                attention[0] if attention is not None else None,
                                copy_to_index,
                            )
                            if position is not None
                        ),
                        default=len(block),
                    )
                    address_lines = block[1:address_end]
                    if address_lines:
                        values["notice_address"].append("\n".join(address_lines))
                values["notice_phone"].append(phone.group(0))
                continue
            if value:
                if field == "cusip" and parse_date(value) is not None:
                    values["event_date"].append(value)
                elif field == "security_class" and _CUSIP_TOKEN_RE.fullmatch(
                    value.strip()
                ):
                    values["cusip"].append(value)
                elif field == "issuer_name" and any(
                    term in value.lower()
                    for term in ("etf", "common stock", "ordinary shares")
                ):
                    values["security_class"].append(value)
                else:
                    values[field].append(value)

    if not values["event_date"]:
        for line in lines[:50]:
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped.split()) <= 4:
                parsed = parse_date(stripped)
                if (
                    parsed is not None
                    and not parsed.ambiguous
                    and "2digit" not in parsed.format_id
                ):
                    values["event_date"].append(stripped)
                    break
            for fmt in SEC_DATE_FORMATS:
                if m := fmt.pattern.search(line):
                    cand = m.group(0)
                    parsed = parse_date(cand)
                    if (
                        parsed is not None
                        and not parsed.ambiguous
                        and "2digit" not in parsed.format_id
                    ):
                        values["event_date"].append(cand)
                        break
            if values["event_date"]:
                break

    if not values["cusip"]:
        for line in lines[:50]:
            stripped = line.strip()
            if _CUSIP_TOKEN_RE.fullmatch(stripped):
                values["cusip"].append(stripped)
                break

    if not values["issuer_name"]:
        for line in lines[:80]:
            m_inline = _RE_INLINE_ISSUER.search(line)
            if m_inline:
                cand = _clean_scalar(m_inline.group("name"))
                if (
                    cand
                    and not _RE_INVALID_ISSUER_NAME.search(cand)
                    and not _RE_SEC_HEADER.search(cand)
                ):
                    values["issuer_name"].append(cand)
                    break
    if not values["issuer_name"]:
        m_fmr = _RE_FMR_HEADER.search(text)
        if m_fmr:
            values["issuer_name"].append(m_fmr.group("issuer").strip())
            if not values["cusip"]:
                values["cusip"].append(m_fmr.group("cusip").strip())
            if not values["security_class"] and "class" in m_fmr.groupdict():
                values["security_class"].append(m_fmr.group("class").strip())
    if not values["issuer_name"] and values["cusip"]:
        target_cusip = values["cusip"][0]
        for idx, l in enumerate(lines[:50]):
            if target_cusip in l:
                m_same = _RE_SAME_LINE_ISSUER.search(l.strip())
                if m_same:
                    same_cand = _clean_scalar(m_same.group("cand"))
                    if _is_plausible_value("issuer_name", same_cand):
                        values["issuer_name"].append(same_cand)
                        break
                prev = idx - 1
                while prev >= 0 and not lines[prev].strip():
                    prev -= 1
                if prev >= 0:
                    cand = lines[prev].strip()
                    if _is_plausible_value("issuer_name", cand):
                        values["issuer_name"].append(cand)
                break

    selected: dict[str, str | None] = {}
    for field, candidates in values.items():
        if field == "event_date" and candidates:
            date_map = {}
            for candidate in candidates:
                p = parse_date(candidate)
                key = p.iso if p is not None else candidate.lower()
                date_map[key] = candidate
            value = next(iter(date_map.values())) if len(date_map) == 1 else None
        elif field == "issuer_name":
            valid_candidates = [
                c
                for c in candidates
                if not _RE_INVALID_ISSUER_NAME.search(c)
                and parse_date(c.strip("() ")) is None
            ]
            unique = {
                " ".join(candidate.lower().split()): candidate
                for candidate in valid_candidates
            }
            value = next(iter(unique.values())) if len(unique) == 1 else None
            if value is None and valid_candidates:
                paren_cands = [
                    c
                    for c in valid_candidates
                    if any(
                        f in c.lower()
                        for f in (
                            "inc",
                            "corp",
                            "l.p.",
                            "llc",
                            "ltd",
                            "fund",
                            "etf",
                            "company",
                            "trust",
                        )
                    )
                ]
                value = paren_cands[0] if paren_cands else valid_candidates[0]
        else:
            unique = {
                " ".join(candidate.lower().split()): candidate
                for candidate in candidates
            }
            value = next(iter(unique.values())) if len(unique) == 1 else None
        if field == "cusip" and value:
            tokens = list(_CUSIP_TOKEN_RE.finditer(value))
            if tokens:
                value = tokens[-1].group(0)
            elif CUSIP_UNAVAILABLE_POLICY.is_missing(value):
                value = None
            elif page_marker := cusip_page_residue_match(value):
                prefix = value[: page_marker.start()]
                tokens = list(_CUSIP_TOKEN_RE.finditer(prefix))
                value = tokens[-1].group(0) if tokens else None
        selected[field] = value
    issuer_address = _address(selected["issuer_address"])
    notice_address = _address(selected["notice_address"])
    return IssuerMetadata(
        issuer_name=selected["issuer_name"],
        issuer_cik=selected["issuer_cik"],
        issuer_address=issuer_address,
        security_class=selected["security_class"],
        cusip=selected["cusip"],
        event_date=selected["event_date"],
        notice_contact=selected["notice_contact"],
        notice_phone=selected["notice_phone"],
        notice_address=notice_address,
        source_text=text,
    )


def _address(value: str | None) -> AddressDetails | None:
    if not value:
        return None
    address_value = value
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) > 1 and ORGANIZATION_SUFFIX_RE.search(lines[0]):
        address_value = "\n".join(lines[1:])
    address_lines = [
        line.strip() for line in address_value.splitlines() if line.strip()
    ]
    street, city, state, zip_code = parse_address_parts(address_value)
    street2 = None
    if city and (suite_city := _RE_SUITE_CITY.fullmatch(city)):
        street2 = suite_city.group("suite").strip()
        city = suite_city.group("city").strip()
    elif city is None and state and zip_code and len(address_lines) > 1:
        city_line = address_lines[-1]
        if "," in city_line:
            city_candidate = city_line.split(",", 1)[0].strip()
            if city_candidate:
                city = city_candidate
                street = "\n".join(address_lines[:-1]) or address_lines[0]
    if street2 is None and "\n" in (street or ""):
        street_lines = [line.strip() for line in street.splitlines() if line.strip()]
        if len(street_lines) > 1:
            street = street_lines[0]
            street2 = "\n".join(street_lines[1:])
    return AddressDetails(
        raw_text=value,
        street1=street or address_value,
        street2=street2,
        city=city,
        state_or_country=state,
        zip_code=zip_code,
    )


def _clean_scalar(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip(" \t\r\n_-=|:"))


def _phone_match(value: str) -> re.Match[str] | None:
    return next(
        (
            match
            for match in _PHONE_RE.finditer(value)
            if sum(char.isdigit() for char in match.group(0)) >= 10
        ),
        None,
    )


__all__ = ["extract_issuer_metadata"]
