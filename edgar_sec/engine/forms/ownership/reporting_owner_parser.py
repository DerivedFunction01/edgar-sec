from __future__ import annotations

import re

from edgar_sec.domain.forms.common.checkmarks import (
    CHECKMARK_MARK_RE,
    MARK_CHARACTERS,
    mark_token_state,
)
from edgar_sec.domain.forms.families.ownership.models import ReportingOwner
from edgar_sec.domain.forms.families.ownership.taxonomy import OWNERSHIP_STATE_CODES
from edgar_sec.domain.taxonomy.jurisdictions import (
    EDGAR_JURISDICTION_CODES,
    edgar_jurisdiction_code,
)
from edgar_sec.engine.forms.common.entities import (
    BARE_BOX_NUM_RE,
    CLEAN_TEMPLATE_RE,
    INTERNATIONAL_ADDRESS_RE,
    IRS_RE,
    NAME_MATCH_RE,
    NON_OWNER_JURISDICTION_RE,
    RELATIONSHIP_TO_ISSUER_RE,
    STATE_ZIP_RE,
    STREET_ANCHOR_RE,
    STRIP_BOX_NUM_RE,
    TITLE_MATCH_RE,
    strip_footnote_markers,
)
from edgar_sec.engine.forms.common.signatures import extract_clean_signatory_name
from edgar_sec.engine.forms.common.tables import parse_address_parts
from edgar_sec.engine.forms.ownership.patterns import is_ownership_boilerplate
from edgar_sec.engine.forms.ownership.relationship_box import RelationshipBox
from edgar_sec.foundation.text.dates import parse_date

_REPORTING_PERSON_PLURAL_RE = re.compile(r"^\(s\)\s*", re.IGNORECASE)
_OFFICER_TITLE_BOUNDARY_RE = re.compile(
    r"\b7\.\s*individual|\bindividual or joint", re.IGNORECASE
)
_FORM_MASTHEAD_RE = re.compile(r"(?i)^f\s*o\s*r\s*m\s*[345]\b")
_STARTS_DIGITS_RE = re.compile(r"^\d+\b")
_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")
_NAME_THEN_ADDRESS_RE = re.compile(r"^name:\s*(.+?)\s+address\s*:", re.IGNORECASE)
_ROLE_TARGETS = (
    ("director", "director"),
    ("officer", "officer"),
    ("ten_percent", "10%"),
    ("other", "other"),
)


def _clean_template_artifacts(text: str) -> str:
    return CLEAN_TEMPLATE_RE.sub("\n", text).strip()


def _resolve_checked_roles(role_cell_text: str) -> dict[str, bool]:
    solved: dict[str, bool] = {key: False for key, _ in _ROLE_TARGETS}
    role_lower = role_cell_text.lower()
    if not any(phrase in role_lower for _, phrase in _ROLE_TARGETS):
        return solved
    for line in role_cell_text.splitlines():
        if not any(char in MARK_CHARACTERS for char in line):
            continue
        line_lower = line.lower()
        marks: list[re.Match[str]] = []
        for match in CHECKMARK_MARK_RE.finditer(line):
            token = match.group(0).strip()
            if mark_token_state(token, allow_bare=True) == "checked":
                marks.append(match)
        if not marks:
            continue
        role_spans = [
            (key, index, index + len(phrase))
            for key, phrase in _ROLE_TARGETS
            if (index := line_lower.find(phrase)) != -1
        ]
        for mark in marks:
            best_key: str | None = None
            min_dist = float("inf")
            for key, start, end in role_spans:
                distance = (
                    start - mark.end()
                    if mark.start() <= start
                    else mark.start() - end + 5
                )
                if distance < min_dist:
                    min_dist = distance
                    best_key = key
            if best_key and min_dist <= 20:
                solved[best_key] = True
    return solved


def parse_reporting_owner(
    cell_text: str,
    role_cell_text: str,
    template_fields: dict[str, str] | None = None,
    reference_year: int | None = None,
    relationship: RelationshipBox | None = None,
) -> ReportingOwner:
    name: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zip_code: str | None = None
    irs_number: str | None = None

    fields = template_fields or {}
    last = fields.get("last")
    first = fields.get("first")
    middle = fields.get("middle")
    if last and first:
        name = f"{last}, {first}" + (f" {middle}" if middle else "")
    street = fields.get("street")
    city = fields.get("city")
    state = fields.get("state")
    zip_code = fields.get("zip")

    raw_lines = _clean_template_artifacts(cell_text).splitlines()
    csz_idx = -1
    street_candidates: list[tuple[int, str]] = []
    name_candidates: list[str] = []

    for index, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if not line or BARE_BOX_NUM_RE.match(line):
            continue
        lower = line.lower()
        if irs_number is None and (irs_match := IRS_RE.search(line)):
            irs_number = irs_match.group(1)
            continue
        if not name and (name_addr := _NAME_THEN_ADDRESS_RE.match(line)):
            candidate = _WHITESPACE_COLLAPSE_RE.sub(" ", name_addr.group(1)).strip(
                ", \n\r*:\xa0"
            )
            if candidate and not is_ownership_boilerplate(candidate):
                name = candidate
            continue
        if (
            not name
            and "reporting person" in lower
            and "i.r.s." not in lower
            and "identification" not in lower
            and "relationship" not in lower
            and "to issuer" not in lower
        ):
            match = NAME_MATCH_RE.search(line)
            if match:
                candidate = match.group(1).strip(", \n\r*:\xa0")
                candidate = _REPORTING_PERSON_PLURAL_RE.sub("", candidate)
                if any(
                    token in candidate.lower()
                    for token in (
                        ", po box",
                        ", p.o. box",
                        ", suite",
                        ", st.",
                        ", street",
                        ", ave",
                        ", road",
                        ", rd.",
                    )
                ):
                    candidate = candidate.split(",")[0].strip()
                if candidate and not is_ownership_boilerplate(candidate):
                    name = candidate
            if not name and index + 1 < len(raw_lines):
                next_line = raw_lines[index + 1].strip()
                if next_line and not any(
                    token in next_line.lower()
                    for token in (
                        "issuer",
                        "ticker",
                        "(last)",
                        "street",
                        "table",
                        "check",
                        "form",
                        "sec ",
                    )
                ):
                    candidate = _WHITESPACE_COLLAPSE_RE.sub(" ", next_line).strip(
                        ", \n\r*:\xa0\t"
                    )
                    if (
                        candidate
                        and not is_ownership_boilerplate(candidate)
                        and not _FORM_MASTHEAD_RE.match(candidate)
                    ):
                        name = candidate
            continue
        if is_ownership_boilerplate(line) or NON_OWNER_JURISDICTION_RE.match(line):
            continue
        if csz_idx == -1 and (state_zip := STATE_ZIP_RE.search(line)):
            state = state_zip.group(1)
            zip_code = state_zip.group(2)
            city_candidate = line[: state_zip.start()].strip(", \n\r")
            if city_candidate:
                city = city_candidate
            csz_idx = index
            continue
        if csz_idx == -1 and (intl := INTERNATIONAL_ADDRESS_RE.match(line)):
            country = edgar_jurisdiction_code(intl.group("country"))
            if country:
                city = intl.group("city")
                zip_code = intl.group("postal")
                csz_idx = index
                continue
        if (
            "$" in line
            or parse_date(line, reference_year=reference_year)
            or IRS_RE.search(line)
        ):
            continue
        cleaned = STRIP_BOX_NUM_RE.sub("", line).strip(", \n\r*")
        if not cleaned:
            continue
        clean_no_footnote = strip_footnote_markers(cleaned)
        has_anchor = bool(STREET_ANCHOR_RE.search(line))
        has_digits = any(char.isdigit() for char in clean_no_footnote)
        starts_digits = bool(_STARTS_DIGITS_RE.match(clean_no_footnote))
        if (
            has_anchor
            and (
                has_digits
                or any(token in lower for token in ("p.o.", "c/o", "penthouse"))
            )
        ) or (
            starts_digits
            and len(clean_no_footnote) < 70
            and not STATE_ZIP_RE.search(line)
        ):
            street_candidates.append((index, clean_no_footnote))
        elif (
            not name
            and 1 <= len(clean_no_footnote.split()) <= 20
            and len(clean_no_footnote) <= 160
            and not _FORM_MASTHEAD_RE.match(clean_no_footnote)
        ):
            name_candidates.append(clean_no_footnote)

    if street_candidates:
        if csz_idx != -1:
            preceding = [
                street for index, street in street_candidates if index < csz_idx
            ]
            street = preceding[-1] if preceding else street_candidates[0][1]
        else:
            street = street_candidates[0][1]

    if street:
        parsed_street, parsed_city, jurisdiction, parsed_zip = parse_address_parts(
            street
        )
        if jurisdiction:
            jurisdiction = edgar_jurisdiction_code(jurisdiction) or jurisdiction
            if jurisdiction in OWNERSHIP_STATE_CODES:
                state = state or jurisdiction
            elif jurisdiction in EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES:
                country = jurisdiction
        street = parsed_street or street
        city = city or parsed_city
        zip_code = zip_code or parsed_zip

    if not name:
        name = next(
            (
                candidate
                for candidate in name_candidates
                if candidate != street and not (city and city in candidate)
            ),
            None,
        )
    if state:
        jurisdiction = edgar_jurisdiction_code(state)
        if jurisdiction in OWNERSHIP_STATE_CODES:
            state = jurisdiction
        elif jurisdiction in EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES:
            country = country or jurisdiction
            state = None

    roles = _resolve_checked_roles(role_cell_text)
    officer_title: str | None = None
    other_text: str | None = None
    if relationship is not None:
        roles = relationship.roles
        officer_title = relationship.officer_title
        other_text = relationship.other_text
    else:
        title_match = TITLE_MATCH_RE.search(role_cell_text)
        officer_title = title_match.group(1).strip() if title_match else None
    if officer_title:
        officer_title = _OFFICER_TITLE_BOUNDARY_RE.split(officer_title)[0].strip()
        if not officer_title or any(
            token in officer_title.lower()
            for token in ("individual or joint", "check applicable", "joint/group")
        ):
            officer_title = None

    return ReportingOwner(
        name=name,
        street=street,
        city=city,
        state=state,
        country=country,
        zip_code=zip_code,
        is_director=roles["director"],
        is_officer=roles["officer"],
        is_ten_percent_owner=roles["ten_percent"],
        is_other=roles["other"],
        officer_title=officer_title,
        other_text=other_text,
        irs_number=irs_number,
    )


__all__ = ["parse_reporting_owner"]
