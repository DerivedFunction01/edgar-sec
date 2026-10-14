"""Metadata extraction for Form 4 filing header, Boxes 1 to 7, and signatures."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.checkmarks import (
    CHECKED_TOKENS,
    CHECKMARK_MARK_RE,
)
from edgar_sec.domain.forms.families.ownership.models import (
    FilingPeriod,
    Form4Metadata,
    Issuer,
    ReportingOwner,
)
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNER_NAME,
)
from edgar_sec.engine.forms.ownership.patterns import (
    AMEND_DATE_CLEAN_RE,
    AMEND_LABEL_RE,
    AMEND_MATCH_RE,
    BARE_BOX_NUM_RE,
    BOX5_SPLIT_RE,
    CLEAN_TEMPLATE_RE,
    IRS_RE,
    ISSUER_LABEL_TERMS,
    ISSUER_TAIL_RE,
    NAME_MATCH_RE,
    NON_OWNER_JURISDICTION_RE,
    PERIOD_MATCH_RE,
    PERIOD_PREFIX_RE,
    PROSE_BOILERPLATE_RE,
    SIG_NAME_RE,
    SIG_PERSON_PREFIX_RE,
    STATE_ZIP_RE,
    STREET_ANCHOR_RE,
    STRIP_BOX_NUM_RE,
    SYMBOL_TAIL_RE,
    TICKER_DASH_RE,
    TICKER_PAREN_RE,
    TITLE_MATCH_RE,
)
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.foundation.text.dates import (
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    parse_date,
)

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
        line_l = line.lower()
        if not any(phrase in line_l for _, phrase in _ROLE_TARGETS):
            continue
        marks: list[re.Match[str]] = []
        for mark_match in CHECKMARK_MARK_RE.finditer(line):
            tok = mark_match.group(0).strip()
            if tok.upper() == "X" or tok in CHECKED_TOKENS:
                marks.append(mark_match)
        if not marks:
            continue
        role_spans: list[tuple[str, int, int]] = []
        for key, phrase in _ROLE_TARGETS:
            idx = line_l.find(phrase)
            if idx != -1:
                role_spans.append((key, idx, idx + len(phrase)))
        for mark in marks:
            best_key: str | None = None
            min_dist = float("inf")
            for key, start, end in role_spans:
                dist = (
                    start - mark.end()
                    if mark.start() <= start
                    else mark.start() - end + 5
                )
                if dist < min_dist:
                    min_dist = dist
                    best_key = key
            if best_key and min_dist <= 20:
                solved[best_key] = True
    return solved


def _parse_reporting_owner(cell_text: str, role_cell_text: str) -> ReportingOwner:
    name: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    irs_number: str | None = None

    cleaned_cell = _clean_template_artifacts(cell_text)
    raw_lines = cleaned_cell.splitlines()

    csz_idx = -1
    street_candidates: list[tuple[int, str]] = []
    name_candidates: list[str] = []

    for idx, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if not line or BARE_BOX_NUM_RE.match(line):
            continue
        lower = line.lower()
        if irs_number is None and (m_irs := IRS_RE.search(line)):
            irs_number = m_irs.group(1)
            continue
        if (
            not name
            and "reporting person" in lower
            and "i.r.s." not in lower
            and "identification" not in lower
        ):
            m = NAME_MATCH_RE.search(line)
            if m:
                cap = m.group(1).strip(", \n\r*")
                if cap and not PROSE_BOILERPLATE_RE.search(cap):
                    name = cap
            continue
        if PROSE_BOILERPLATE_RE.search(line) or NON_OWNER_JURISDICTION_RE.match(line):
            continue
        if csz_idx == -1 and (sz := STATE_ZIP_RE.search(line)):
            state = sz.group(1)
            zip_code = sz.group(2)
            city_cand = line[: sz.start()].strip(", \n\r")
            if city_cand:
                city = city_cand
            csz_idx = idx
            continue
        if "$" in line or parse_date(line) or IRS_RE.search(line):
            continue
        cleaned = STRIP_BOX_NUM_RE.sub("", line).strip(", \n\r*")
        if not cleaned:
            continue
        has_anchor = bool(STREET_ANCHOR_RE.search(line))
        has_digits = any(c.isdigit() for c in line)
        if (
            has_anchor
            and (has_digits or any(k in lower for k in ("p.o.", "c/o", "penthouse")))
        ) or (has_digits and len(cleaned) < 70 and not STATE_ZIP_RE.search(line)):
            street_candidates.append((idx, cleaned))
        elif not name and 1 <= len(cleaned.split()) <= 6:
            name_candidates.append(cleaned)

    if street_candidates:
        if csz_idx != -1:
            before_csz = [s for idx, s in street_candidates if idx < csz_idx]
            street = before_csz[-1] if before_csz else street_candidates[0][1]
        else:
            street = street_candidates[0][1]

    if not name and name_candidates:
        for cand in name_candidates:
            if cand != street and not (city and city in cand):
                name = cand
                break

    roles = _resolve_checked_roles(role_cell_text)
    title_match = TITLE_MATCH_RE.search(role_cell_text)
    officer_title = title_match.group(1).strip() if title_match else None

    return ReportingOwner(
        name=name,
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
        is_director=roles["director"],
        is_officer=roles["officer"],
        is_ten_percent_owner=roles["ten_percent"],
        is_other=roles["other"],
        officer_title=officer_title,
        irs_number=irs_number,
    )


def _parse_issuer(cell_text: str) -> Issuer:
    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]
    cand = ""
    last_label_idx = -1
    for idx, line in enumerate(lines):
        if any(term in line.lower() for term in ISSUER_LABEL_TERMS):
            last_label_idx = idx
            m = SYMBOL_TAIL_RE.search(line)
            if m:
                tail = m.group(1).strip()
                if tail and tail.lower() not in ("or", "and", "or trading symbol"):
                    cand = tail
                    break
            m_iss = ISSUER_TAIL_RE.search(line)
            if m_iss:
                tail = m_iss.group(1).strip()
                if tail and not any(
                    k in tail.lower() for k in ("trading symbol", "and address")
                ):
                    cand = tail
                    break
    if not cand and last_label_idx != -1 and last_label_idx + 1 < len(lines):
        cand = lines[last_label_idx + 1]
    if not cand and lines:
        cand = lines[-1]

    name: str | None = None
    ticker: str | None = None
    if cand:
        m_paren = TICKER_PAREN_RE.search(cand)
        if m_paren:
            name = cand[: m_paren.start()].rstrip(" ,-")
            ticker = m_paren.group(1).strip("()\"“”',.-")
            if " and " in ticker:
                ticker = ticker.split(" and ")[0].strip()
        else:
            m_dash = TICKER_DASH_RE.search(cand)
            if m_dash:
                name = cand[: m_dash.start()].rstrip(" ,-")
                ticker = m_dash.group(1).strip("()\"“”',.-")
            elif " " in cand:
                parts = cand.rsplit(" ", 1)
                last = parts[1].strip("()\"“”',.-")
                if (
                    1 <= len(last) <= 6
                    and last.isupper()
                    and last.lower() not in LEGAL_FORMS
                ):
                    name = parts[0].rstrip(" ,-")
                    ticker = last
                else:
                    name = cand.rstrip(" ,-")
            else:
                name = cand.rstrip(" ,-")

        if not ticker:
            for line in lines:
                if line == cand:
                    continue
                if any(
                    term in line.lower()
                    for term in ("issuer", "trading", "ticker", "i.r.s.")
                ):
                    continue
                m_sub = TICKER_PAREN_RE.search(line)
                if m_sub:
                    ticker = m_sub.group(1).strip("()\"“”',.-")
                    if " and " in ticker:
                        ticker = ticker.split(" and ")[0].strip()
                    break
                stripped = line.strip("()\"“”',.-")
                if (
                    1 <= len(stripped) <= 6
                    and stripped.isupper()
                    and stripped.lower() not in LEGAL_FORMS
                ):
                    ticker = stripped
                    break

    if name:
        name = STRIP_BOX_NUM_RE.sub("", name).strip()

    irs_match = IRS_RE.search(cell_text)
    irs_number = irs_match.group(1) if irs_match else None

    return Issuer(
        name=name if name else None,
        trading_symbol=ticker if ticker else None,
        irs_number=irs_number,
    )


def _parse_period(cell_text: str) -> FilingPeriod:
    m = BOX5_SPLIT_RE.search(cell_text)
    box4_text = cell_text[: m.start()] if m else cell_text
    box5_text = cell_text[m.start() :] if m else ""

    period: str | None = None
    for raw_line in box4_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = PERIOD_PREFIX_RE.sub("", line).strip()
        if cleaned and any(c.isdigit() for c in cleaned):
            period = cleaned
            break

    amend_date: str | None = None
    if box5_text:
        for raw_line in box5_text.splitlines():
            line = raw_line.strip()
            if not line or AMEND_LABEL_RE.match(line):
                continue
            cleaned = AMEND_DATE_CLEAN_RE.sub("", line).strip()
            if cleaned and any(c.isdigit() for c in cleaned):
                amend_date = cleaned
                break

    is_amendment = bool(amend_date and any(c.isdigit() for c in amend_date))

    return FilingPeriod(
        period_of_report=period,
        is_amendment=is_amendment,
        date_of_original=amend_date if is_amendment else None,
    )


def parse_metadata(
    boxes_section: ClassifiedSection | None,
    signatures_section: ClassifiedSection | None,
) -> Form4Metadata:
    """Extract structured Box 1-7 metadata and signature records."""
    if boxes_section is None:
        return Form4Metadata(
            issuer=Issuer(),
            reporting_owner=ReportingOwner(),
            period=FilingPeriod(),
        )

    rows = boxes_section.resolved_grid.rows
    owner_lines: list[str] = []
    owner_seen: set[str] = set()
    role_lines: list[str] = []
    role_seen: set[str] = set()
    issuer_cell = ""
    period_cell = ""

    for r_idx, row in enumerate(rows):
        if any(
            c
            and (
                "table i" in (c_low := c.lower())
                or "table ii" in c_low
                or "non-derivative" in c_low
            )
            for c in row
        ):
            break
        for cell in row[:2]:
            s = cell.strip()
            s_low = s.lower()
            if any(
                term in s_low
                for term in (
                    "issuer name",
                    "trading symbol",
                    "statement for",
                    "4. statement",
                )
            ):
                continue
            if s and s not in owner_seen:
                owner_seen.add(s)
                owner_lines.append(s)
        for c_idx, cell in enumerate(row):
            if not cell:
                continue
            lower = cell.lower()
            if "issuer name" in lower and not issuer_cell:
                cand = cell
                if r_idx + 1 < len(rows):
                    below = rows[r_idx + 1][c_idx].strip()
                    if below and not any(
                        k in below.lower()
                        for k in (
                            "statement for",
                            "relationship",
                            "reporting person",
                            "table i",
                        )
                    ):
                        cand = f"{cell}\n{below}"
                issuer_cell = cand
            elif (
                "statement for" in lower or ("4." in lower and "month" in lower)
            ) and not period_cell:
                cand = cell
                if r_idx + 1 < len(rows):
                    below = rows[r_idx + 1][c_idx].strip()
                    if (
                        below
                        and any(char.isdigit() for char in below)
                        and not any(
                            k in below.lower() for k in ("relationship", "table i")
                        )
                    ):
                        cand = f"{cell}\n{below}"
                period_cell = cand
            elif "relationship" in lower or any(
                term in lower for term in ("director", "officer", "10%")
            ):
                s = cell.strip()
                if s and s not in role_seen:
                    role_seen.add(s)
                    role_lines.append(s)

    owner = _parse_reporting_owner("\n".join(owner_lines), "\n".join(role_lines))
    issuer = _parse_issuer(issuer_cell)
    period = _parse_period(period_cell)

    sig_name: str | None = None
    sig_date: str | None = None
    if signatures_section is not None:
        sig_cells: list[str] = [
            c.strip()
            for r in signatures_section.resolved_grid.rows
            for c in r
            if c and c.strip()
        ]
        sig_text = "\n".join(sig_cells)
        m_date = RE_FULL_DATE.search(sig_text) or NUMERIC_DATE_RE.search(sig_text)
        if m_date:
            sig_date = m_date.group(0).strip()
        m_sig = RE_CONFORMED_SIGNER_NAME.search(sig_text)
        if m_sig and (cand_name := m_sig.group(1).strip(" ,.-")):
            sig_name = cand_name
        elif (m_pref := SIG_PERSON_PREFIX_RE.search(sig_text)) and (
            cand_name := m_pref.group(1).strip(" ,.-")
        ):
            sig_name = cand_name
        elif (m_name := SIG_NAME_RE.search(sig_text)) and (
            cand_name := m_name.group(1).strip(" ,.-")
        ):
            sig_name = cand_name

    return Form4Metadata(
        issuer=issuer,
        reporting_owner=owner,
        period=period,
        signature_name=sig_name,
        signature_date=sig_date,
    )


__all__ = [
    "parse_metadata",
]
