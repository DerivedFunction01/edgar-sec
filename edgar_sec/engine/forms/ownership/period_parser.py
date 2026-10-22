from __future__ import annotations

import re

from edgar_sec.domain.forms.families.ownership.models import FilingPeriod
from edgar_sec.engine.forms.common.periods import (
    AMEND_DATE_CLEAN_RE,
    AMEND_LABEL_RE,
    BOX5_SPLIT_RE,
    PERIOD_PREFIX_RE,
)
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE, RE_FULL_DATE

_DIGIT_CHAR_RE = re.compile(r"\d")


def parse_period(cell_text: str) -> FilingPeriod:
    match = BOX5_SPLIT_RE.search(cell_text)
    box4_text = cell_text[: match.start()] if match else cell_text
    box5_text = cell_text[match.start() :] if match else ""

    cleaned_lines = [
        PERIOD_PREFIX_RE.sub("", raw_line.strip()).strip()
        for raw_line in box4_text.splitlines()
        if raw_line.strip()
    ]
    period: str | None = None
    for cleaned in cleaned_lines:
        if NUMERIC_DATE_RE.search(cleaned) or RE_FULL_DATE.search(cleaned):
            period = cleaned
            break
    if period is None:
        for cleaned in cleaned_lines:
            if cleaned and len(_DIGIT_CHAR_RE.findall(cleaned)) >= 2:
                period = cleaned
                break

    amend_date: str | None = None
    if box5_text:
        for raw_line in box5_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if AMEND_LABEL_RE.match(line):
                m_label_date = NUMERIC_DATE_RE.search(line) or RE_FULL_DATE.search(line)
                if m_label_date:
                    amend_date = m_label_date.group(0).strip()
                    break
                continue
            cleaned = AMEND_DATE_CLEAN_RE.sub("", line).strip()
            if cleaned and any(char.isdigit() for char in cleaned):
                amend_date = cleaned
                break

    is_amendment = bool(amend_date and any(char.isdigit() for char in amend_date))
    if not period and is_amendment:
        period = amend_date
    return FilingPeriod(
        period_of_report=period,
        is_amendment=is_amendment,
        date_of_original=amend_date if is_amendment else None,
    )


__all__ = ["parse_period"]
