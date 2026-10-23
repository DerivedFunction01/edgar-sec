"""Extraction of issuer and reporting-person cover details."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.models import (
    IssuerInformation,
    ReportingPerson,
)
from edgar_sec.engine.forms.common.entities import IRS_RE, STATE_ZIP_RE
from edgar_sec.engine.forms.common.tables import (
    address_from_column_headers,
    address_from_inline_cells,
    clean_field_candidate,
    extract_labeled_field,
    parse_address_parts,
)
from edgar_sec.engine.forms.form144.patterns import (
    PHONE_RE,
    SEC_FILE_BARE_RE,
    SEC_FILE_LABEL_RE,
)
from edgar_sec.engine.forms.form144.sections import ClassifiedSection

_STREET_NUM_PAREN_RE = re.compile(r"^\d+\s*\([a-z]\)", re.IGNORECASE)

_ISSUER_LABELS = ("name of issuer", "1 (a)", "1(a)")
_SELLER_LABELS = (
    "person for whose account the securities are to be sold",
    "person for whose account sold",
    "person for whose account",
    "2 (a)",
    "2(a)",
)
_BOILERPLATE_NAMES = frozenset(
    {
        "instructions",
        "street",
        "city",
        "state",
        "zip code",
        "sec use only",
        "area code number",
        "telephone",
        "name of issuer",
    }
)
_HEADER_WORDS = frozenset(
    {
        "address",
        "area",
        "city",
        "code",
        "instructions",
        "issuer",
        "name",
        "number",
        "of",
        "only",
        "sec",
        "state",
        "street",
        "telephone",
        "use",
        "zip",
    }
)


def _is_boilerplate_name(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.strip().lower()
    if lowered in _BOILERPLATE_NAMES or lowered.startswith("("):
        return True
    words = [word.strip(".,") for word in lowered.split()]
    return bool(words) and all(word in _HEADER_WORDS for word in words)


_ISSUER_EXCLUDED = ("irs", "sec file", "relationship", "address", "telephone")
_SELLER_EXCLUDED = ("irs", "relationship", "address", "issuer", "telephone")
_RELATIONSHIPS = (
    "officer",
    "director",
    "10% stockholder",
    "affiliate",
    "trustee",
    "other",
)
_RELATIONSHIP_CANONICAL = {
    "officer": "Officer",
    "director": "Director",
    "10% stockholder": "10% Stockholder",
    "affiliate": "Provide any other relationship not mentioned above",
    "trustee": "Provide any other relationship not mentioned above",
    "other": "Provide any other relationship not mentioned above",
}


def _labeled_address(
    rows: tuple[tuple[str, ...], ...], row_idx: int, label: str
) -> tuple[str | None, str | None, str | None, str | None] | None:
    labels = rows[row_idx]
    for col_idx, cell in enumerate(labels):
        lines = [line.strip() for line in cell.splitlines() if line.strip()]
        label_line_idx = next(
            (i for i, line in enumerate(lines) if label in line.lower()), None
        )
        if label_line_idx is None:
            continue
        inline = address_from_inline_cells(labels)
        if inline:
            return inline
        label_line = lines[label_line_idx]
        label_tail = label_line[label_line.lower().find(label) + len(label) :]
        zip_label_idx = label_tail.lower().find("zip code")
        if zip_label_idx >= 0:
            label_tail = label_tail[zip_label_idx + len("zip code") :]
        if STATE_ZIP_RE.search(label_tail):
            return parse_address_parts(label_tail)
        if row_idx + 1 < len(rows):
            columns = address_from_column_headers(labels, rows[row_idx + 1])
            if columns:
                return columns
        row_tail = " ".join(labels[col_idx + 1 :])
        if STATE_ZIP_RE.search(row_tail):
            return parse_address_parts(row_tail)
        following_lines = lines[label_line_idx + 1 :]
        if any(STATE_ZIP_RE.search(line) for line in following_lines):
            return parse_address_parts(" ".join(following_lines))
        value_lines = [
            line
            for line in following_lines
            if not any(
                line.lower().strip() == term
                for term in ("street", "city", "state", "zip code")
            )
        ]
        if value_lines:
            return parse_address_parts(" ".join(value_lines))
        if row_idx + 1 < len(rows):
            candidate = " ".join(
                part.strip() for part in rows[row_idx + 1] if part.strip()
            )
            return parse_address_parts(candidate)
        return None
    return None


def _recover_address_street(
    rows: tuple[tuple[str, ...], ...],
    row_idx: int,
    parts: tuple[str | None, str | None, str | None, str | None] | None,
) -> tuple[str | None, str | None, str | None, str | None] | None:
    if parts is None or parts[0] or row_idx + 1 >= len(rows):
        return parts
    labels = rows[row_idx]
    for address_idx, label in enumerate(labels[:-1]):
        if (
            "address" not in label.lower()
            or "street" not in labels[address_idx + 1].lower()
        ):
            continue
        for candidate_row in rows[row_idx + 1 : row_idx + 9]:
            if address_idx >= len(candidate_row):
                continue
            street = candidate_row[address_idx].strip()
            if not street or _STREET_NUM_PAREN_RE.match(street):
                continue
            if any(
                phrase in street.lower()
                for phrase in ("name of", "relationship to issuer", "zip code")
            ):
                continue
            aligned = address_from_column_headers(labels, candidate_row)
            if aligned:
                return (
                    street,
                    parts[1] or aligned[1],
                    parts[2] or aligned[2],
                    parts[3] or aligned[3],
                )
            return street, parts[1], parts[2], parts[3]
    return parts


def parse_cover_box_1_2(
    section: ClassifiedSection | None,
) -> tuple[IssuerInformation, ReportingPerson]:
    """Extract issuer and reporting person details from Form 144 Cover Boxes 1 & 2."""
    if section is None:
        return IssuerInformation(), ReportingPerson()

    grid = section.resolved_grid
    issuer_name = extract_labeled_field(grid, _ISSUER_LABELS, excluded=_ISSUER_EXCLUDED)
    if _is_boilerplate_name(issuer_name):
        issuer_name = None
    if not issuer_name and grid.rows:
        for row in grid.rows[:3]:
            for cell in row:
                c = cell.strip()
                if not c:
                    continue
                c_low = c.lower()
                if any(
                    k in c_low
                    for k in (
                        "omb",
                        "united states",
                        "form 144",
                        "notice of proposed",
                        "sec use only",
                        "document sequence",
                        "cusip",
                    )
                ):
                    continue
                if any(lbl in c_low for lbl in _ISSUER_LABELS) or any(
                    term in c_low for term in _ISSUER_EXCLUDED
                ):
                    continue
                cand = clean_field_candidate(c, _ISSUER_EXCLUDED)
                if (
                    cand
                    and len(cand) >= 3
                    and not any(char.isdigit() for char in cand)
                    and not _is_boilerplate_name(cand)
                ):
                    issuer_name = cand
                    break
            if issuer_name:
                break

    seller_name = extract_labeled_field(grid, _SELLER_LABELS, excluded=_SELLER_EXCLUDED)
    if _is_boilerplate_name(seller_name):
        seller_name = None

    irs_num: str | None = None
    sec_file: str | None = None
    issuer_street: str | None = None
    issuer_city: str | None = None
    issuer_state: str | None = None
    issuer_zip: str | None = None
    phone: str | None = None
    seller_street: str | None = None
    seller_city: str | None = None
    seller_state: str | None = None
    seller_zip: str | None = None
    relationships: list[str] = []
    detected_titles: list[str] = []
    seller_relationship_labeled = False

    for row_idx, row in enumerate(grid.rows):
        row_text = " ".join(c.strip() for c in row if c.strip())
        lower_row = row_text.lower()

        if "relationship to issuer" in lower_row:
            seller_relationship_labeled = True

        irs_match = IRS_RE.search(row_text)
        if irs_match and not irs_num:
            irs_num = irs_match.group(1)
        sec_label_match = SEC_FILE_LABEL_RE.search(row_text)
        if sec_label_match and not sec_file:
            sec_file = sec_label_match.group(1)
        elif not sec_file:
            for candidate in SEC_FILE_BARE_RE.findall(row_text):
                if candidate != irs_num and "3235" not in candidate:
                    sec_file = candidate
                    break

        phone_text = " ".join(
            lower_row.replace("area code", "").replace("number", "").split()
        )
        phone_match = PHONE_RE.search(phone_text)
        if phone_match and not phone:
            phone = phone_match.group(0)

        if "address of issuer" in lower_row and issuer_street is None:
            parts = _labeled_address(grid.rows, row_idx, "address of issuer")
            parts = _recover_address_street(grid.rows, row_idx, parts)
            if parts:
                issuer_street, issuer_city, issuer_state, issuer_zip = parts

        if "address" in lower_row and (
            "person for whose" in lower_row
            or (
                seller_name
                and "street" in lower_row
                and "zip code" in lower_row
                and "issuer" not in lower_row
            )
        ):
            parts = _labeled_address(grid.rows, row_idx, "address")
            parts = _recover_address_street(grid.rows, row_idx, parts)
            if parts and parts[1] is None:
                address_row = " ".join(grid.rows[row_idx])
                zip_label = address_row.lower().rfind("zip code")
                if zip_label >= 0:
                    recovered = parse_address_parts(
                        address_row[zip_label + len("zip code") :]
                    )
                    if recovered[1]:
                        parts = recovered
            if parts and not seller_street:
                seller_street, seller_city, seller_state, seller_zip = parts

        for token in _RELATIONSHIPS:
            if token in lower_row:
                canonical = _RELATIONSHIP_CANONICAL[token]
                if canonical not in relationships:
                    relationships.append(canonical)
                title = token.title()
                if title not in detected_titles:
                    detected_titles.append(title)

    if seller_name and seller_relationship_labeled:
        for relationship in detected_titles:
            suffix = f" {relationship}"
            if seller_name.lower().endswith(suffix.lower()):
                seller_name = seller_name[: -len(suffix)].rstrip()
                break

    issuer = IssuerInformation(
        name=issuer_name,
        sec_file_number=sec_file,
        street1=issuer_street,
        city=issuer_city,
        state_or_country=issuer_state,
        zip_code=issuer_zip,
        contact_phone=phone,
    )
    person = ReportingPerson(
        name=seller_name,
        street1=seller_street,
        city=seller_city,
        state_or_country=seller_state,
        zip_code=seller_zip,
        relationships=tuple(relationships),
    )
    return issuer, person


__all__ = ["parse_cover_box_1_2"]
