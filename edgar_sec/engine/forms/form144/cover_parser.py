"""Extraction of issuer and reporting-person cover details."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.models import (
    IssuerInformation,
    ReportingPerson,
)
from edgar_sec.engine.forms.common.entities import IRS_RE, STATE_ZIP_RE
from edgar_sec.engine.forms.form144.patterns import (
    PHONE_RE,
    SEC_FILE_BARE_RE,
    SEC_FILE_LABEL_RE,
)
from edgar_sec.engine.forms.form144.sections import ClassifiedSection


def _clean_candidate(text: str, excluded: tuple[str, ...]) -> str | None:
    value = text.strip(" \t\r\n:;,-")
    lower = value.lower()
    if len(value) < 2 or any(term in lower for term in excluded):
        return None
    return value


def _value_for_label(
    rows: tuple[tuple[str, ...], ...],
    row_idx: int,
    col_idx: int,
    label: str,
    excluded: tuple[str, ...],
) -> str | None:
    row = rows[row_idx]
    cell = row[col_idx]
    lines = [line.strip() for line in cell.splitlines() if line.strip()]
    for line_idx, line in enumerate(lines):
        lower = line.lower()
        if label not in lower:
            continue
        tail = line[lower.find(label) + len(label) :]
        if ")" in tail:
            tail = tail[tail.rfind(")") + 1 :]
        value = _clean_candidate(tail, excluded)
        if value:
            return value
        value_lines: list[str] = []
        for candidate in lines[line_idx + 1 :]:
            if candidate.lower().strip(" .:;") == "are to be sold":
                continue
            value = _clean_candidate(candidate, excluded)
            if not value:
                break
            value_lines.append(value)
        if value_lines:
            return " ".join(value_lines)

    if col_idx + 1 < len(row):
        value = _clean_candidate(row[col_idx + 1], excluded)
        if value:
            return value
    if row_idx + 1 < len(rows):
        for candidate in rows[row_idx + 1]:
            value = _clean_candidate(candidate, excluded)
            if not value:
                continue
            marker = value.replace(" ", "").lower()
            if marker in {"(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)"} or (
                len(marker) == 4
                and marker[0].isdigit()
                and marker[1] == "("
                and marker[2] in "abcdefg"
                and marker[3] == ")"
            ):
                continue
            return value
    return None


def _address_parts(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    match = STATE_ZIP_RE.search(text)
    if not match:
        return text.strip() or None, None, None, None
    prefix = text[: match.start()].strip().rstrip(",")
    pieces = [piece.strip() for piece in prefix.split(",") if piece.strip()]
    city = pieces.pop() if len(pieces) > 1 else None
    street = ", ".join(pieces) if pieces else prefix or None
    return street, city, match.group(1), match.group(2)


def _address_from_columns(
    labels: tuple[str, ...], values: tuple[str, ...]
) -> tuple[str | None, str | None, str | None, str | None] | None:
    field_terms = ("street", "city", "state", "zip")
    indexes: list[int] = []
    for term in field_terms:
        matches = [i for i, cell in enumerate(labels) if term in cell.lower()]
        if len(matches) != 1:
            return None
        indexes.append(matches[0])
    if len(set(indexes)) != len(indexes) or any(i >= len(values) for i in indexes):
        return None
    street, city, state, zip_code = (values[i].strip() or None for i in indexes)
    return street, city, state, zip_code


def _address_from_inline_cells(
    row: tuple[str, ...],
) -> tuple[str | None, str | None, str | None, str | None] | None:
    fields: dict[str, str] = {}
    terms = ("street", "city", "state", "zip code")
    for term in terms:
        for cell in row:
            lines = [line.strip() for line in cell.splitlines() if line.strip()]
            for line_idx, line in enumerate(lines):
                lower = line.lower()
                if term not in lower:
                    continue
                if sum(candidate in lower for candidate in terms) > 1:
                    continue
                tail = line[lower.find(term) + len(term) :]
                value = _clean_candidate(tail, ("street", "city", "state", "zip code"))
                if value:
                    fields[term] = value
                    break
                if line_idx + 1 < len(lines):
                    value = _clean_candidate(
                        lines[line_idx + 1], ("street", "city", "state", "zip code")
                    )
                    if value:
                        fields[term] = value
                        break
            if term in fields:
                break
    if not fields:
        return None
    state_zip = STATE_ZIP_RE.search(" ".join(row))
    state = fields.get("state")
    zip_code = fields.get("zip code")
    if state_zip:
        state = state or state_zip.group(1)
        zip_code = zip_code or state_zip.group(2)
    return fields.get("street"), fields.get("city"), state, zip_code


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
        inline = _address_from_inline_cells(labels)
        if inline:
            return inline
        label_line = lines[label_line_idx]
        label_tail = label_line[label_line.lower().find(label) + len(label) :]
        zip_label_idx = label_tail.lower().find("zip code")
        if zip_label_idx >= 0:
            label_tail = label_tail[zip_label_idx + len("zip code") :]
        if STATE_ZIP_RE.search(label_tail):
            return _address_parts(label_tail)
        if row_idx + 1 < len(rows):
            columns = _address_from_columns(labels, rows[row_idx + 1])
            if columns:
                return columns
        row_tail = " ".join(labels[col_idx + 1 :])
        if STATE_ZIP_RE.search(row_tail):
            return _address_parts(row_tail)
        following_lines = lines[label_line_idx + 1 :]
        if any(STATE_ZIP_RE.search(line) for line in following_lines):
            return _address_parts(" ".join(following_lines))
        value_lines = [
            line
            for line in following_lines
            if not any(
                line.lower().strip() == term
                for term in ("street", "city", "state", "zip code")
            )
        ]
        if value_lines:
            return _address_parts(" ".join(value_lines))
        if row_idx + 1 < len(rows):
            candidate = " ".join(
                part.strip() for part in rows[row_idx + 1] if part.strip()
            )
            return _address_parts(candidate)
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
            if not street or re.match(r"^\d+\s*\([a-z]\)", street, re.IGNORECASE):
                continue
            if any(
                phrase in street.lower()
                for phrase in ("name of", "relationship to issuer", "zip code")
            ):
                continue
            aligned = _address_from_columns(labels, candidate_row)
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
    if section is None:
        return IssuerInformation(), ReportingPerson()

    grid = section.resolved_grid
    issuer_name: str | None = None
    irs_num: str | None = None
    sec_file: str | None = None
    issuer_street: str | None = None
    issuer_city: str | None = None
    issuer_state: str | None = None
    issuer_zip: str | None = None
    phone: str | None = None
    seller_name: str | None = None
    seller_street: str | None = None
    seller_city: str | None = None
    seller_state: str | None = None
    seller_zip: str | None = None
    relationships: list[str] = []
    seller_relationship_labeled = False

    for row_idx, row in enumerate(grid.rows):
        row_text = " ".join(c.strip() for c in row if c.strip())
        lower_row = row_text.lower()

        for c_idx, cell in enumerate(row):
            c_clean = cell.strip()
            c_lower = c_clean.lower()
            if not c_clean:
                continue
            if (
                "name of issuer" in c_lower or "1 (a)" in c_lower or "1(a)" in c_lower
            ) and issuer_name is None:
                issuer_name = _value_for_label(
                    grid.rows,
                    row_idx,
                    c_idx,
                    "name of issuer",
                    ("irs", "sec file", "relationship", "address", "telephone"),
                )
            if (
                "person for whose account" in c_lower
                or "2 (a)" in c_lower
                or "2(a)" in c_lower
            ) and seller_name is None:
                seller_relationship_labeled |= "relationship to issuer" in c_lower
                seller_label = next(
                    (
                        label
                        for label in (
                            "person for whose account the securities are to be sold",
                            "person for whose account sold",
                            "person for whose account",
                        )
                        if label in c_lower
                    ),
                    None,
                )
                if seller_label:
                    seller_name = _value_for_label(
                        grid.rows,
                        row_idx,
                        c_idx,
                        seller_label,
                        ("irs", "relationship", "address", "issuer", "telephone"),
                    )

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
        if "relationship to issuer" in lower_row:
            seller_relationship_labeled = True
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
                    recovered = _address_parts(
                        address_row[zip_label + len("zip code") :]
                    )
                    if recovered[1]:
                        parts = recovered
            if parts and not seller_street:
                seller_street, seller_city, seller_state, seller_zip = parts

        for relationship in (
            "officer",
            "director",
            "10% stockholder",
            "affiliate",
            "trustee",
            "other",
        ):
            if relationship in lower_row and relationship.title() not in relationships:
                relationships.append(relationship.title())

    if seller_name and seller_relationship_labeled:
        for relationship in relationships:
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
