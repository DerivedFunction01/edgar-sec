"""Pins for the homed period-phrase recognizers in text/dates.
PERIOD_ENDED_RE keeps the narrower alternation its consumers were built on;
the wider alternation lives only in the PERIOD_ENDED_PAT fragment.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.text.dates import (
    PERIOD_ENDED_PAT,
    PERIOD_ENDED_RE,
    REPORTING_PERIOD_CAPTION_RE,
    REPORTING_PERIOD_LABEL_RE,
    REPORTING_PERIOD_VALUE_RE,
    REPORT_QUARTER_ENDED_RE,
)


def test_period_ended_re_matches_period_and_fiscal_year() -> None:
    assert PERIOD_ENDED_RE.search("For the period ended March 31, 2026")
    assert PERIOD_ENDED_RE.search("fiscal year ended December 31, 2025")


def test_period_ended_re_keeps_the_narrower_alternation() -> None:
    assert PERIOD_ENDED_RE.search("quarter ended March 31") is None


def test_period_ended_pat_composes_the_wide_alternation() -> None:
    composed = re.compile(PERIOD_ENDED_PAT + r"\s+(.+)", re.IGNORECASE)
    match = composed.search("for the quarter ended March 31, 2026")
    assert match is not None
    assert match.group(1) == "March 31, 2026"


def test_reporting_period_caption_and_value() -> None:
    head = "Date of reporting period: March 31, 2026"
    assert REPORTING_PERIOD_CAPTION_RE.search(head)
    value = REPORTING_PERIOD_VALUE_RE.search(head)
    assert value is not None
    assert value.group(1) == "March 31, 2026"


def test_reporting_period_label_captures_the_rest() -> None:
    match = REPORTING_PERIOD_LABEL_RE.search("reporting period: 2026-03-31")
    assert match is not None
    assert match.group(1) == "2026-03-31"


def test_report_quarter_ended_both_spellings() -> None:
    plain = REPORT_QUARTER_ENDED_RE.search(
        "Report for the Quarter Ended: March 31, 2026"
    )
    assert plain is not None
    assert plain.group(1) == "March 31, 2026"
    calendar = REPORT_QUARTER_ENDED_RE.search(
        "Report for the Calendar Year or Quarter Ended: March 31, 2026"
    )
    assert calendar is not None
    assert calendar.group(1) == "March 31, 2026"
