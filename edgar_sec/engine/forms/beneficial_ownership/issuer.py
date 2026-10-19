"""Extracts issuer and notice metadata from the cover header slice."""

from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    IssuerMetadata,
)
from edgar_sec.engine.forms.common.tables import parse_address_parts

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "issuer_name": ("name of issuer", "issuer name", "issuer"),
    "issuer_cik": ("cik of issuer", "issuer cik", "cik number of issuer"),
    "issuer_address": ("address of issuer", "issuer address"),
    "security_class": (
        "title of class of securities",
        "title of class",
        "class of securities",
    ),
    "cusip": ("cusip number", "cusip no.", "cusip"),
    "event_date": (
        "date of event which requires filing of this statement",
        "date of event requiring filing of this statement",
        "date of event",
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
_LABEL_CONTINUATIONS = frozenset(
    {
        "and",
        "authorized",
        "communications",
        "for",
        "from",
        "of",
        "the",
        "this",
        "to",
        "which",
        "who",
        "with",
    }
)


def _label_and_value(line: str) -> tuple[str, str] | None:
    original = line.strip()
    normalized = " ".join(original.strip("() \t").lower().split())
    for label in _ALL_LABELS:
        if normalized == label:
            return label, ""
        if normalized.startswith(label) and len(normalized) > len(label):
            boundary = normalized[len(label)]
            tail = normalized[len(label) :].lstrip()
            if boundary in ":.-|" or (
                boundary.isspace()
                and tail.split(maxsplit=1)[0] not in _LABEL_CONTINUATIONS
                and not (original.startswith("(") and not original.endswith(")"))
            ):
                value_start = original.lower().find(label) + len(label)
                return label, original[value_start:].lstrip(" \t:.-|)")
    return None


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
        if (
            not value
            and parenthesized
            and field in {"issuer_name", "security_class", "cusip", "event_date"}
        ):
            previous_index = index - 1
            while previous_index >= 0 and not lines[previous_index].strip():
                previous_index -= 1
            if previous_index >= 0 and _label_sequence(lines, previous_index) is None:
                value = lines[previous_index].strip()
        if not value:
            for candidate_index in range(label_end, min(label_end + 3, len(lines))):
                next_line = lines[candidate_index]
                if not next_line.strip():
                    continue
                if _label_sequence(lines, candidate_index) is not None:
                    break
                value = next_line.strip()
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
            values[field].append(value.strip())
        index = max(index + 1, label_end)

    selected: dict[str, str | None] = {}
    for field, candidates in values.items():
        unique = {
            " ".join(candidate.lower().split()): candidate for candidate in candidates
        }
        selected[field] = next(iter(unique.values())) if len(unique) == 1 else None
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
    street, city, state, zip_code = parse_address_parts(value)
    return AddressDetails(
        raw_text=value,
        street1=street or value,
        city=city,
        state_or_country=state,
        zip_code=zip_code,
    )


__all__ = ["extract_issuer_metadata"]
