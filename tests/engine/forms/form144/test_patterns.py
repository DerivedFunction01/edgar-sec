"""Tests for Form 144 regex patterns."""

from edgar_sec.engine.forms.common.entities import EXCHANGE_RE
from edgar_sec.engine.forms.form144.patterns import (
    NOTICE_DATE_LABEL_RE,
    PLAN_ADOPTION_RE,
    SEC_FILE_LABEL_RE,
)


def test_exchange_patterns():
    match = EXCHANGE_RE.search("Traded on NYSE exchange")
    assert match is not None and match.group(1).upper() == "NYSE"


def test_sec_file_patterns():
    match = SEC_FILE_LABEL_RE.search("S.E.C. FILE NO.: 001-12345")
    assert match is not None and match.group(1) == "001-12345"


def test_plan_and_notice_patterns():
    m_notice = NOTICE_DATE_LABEL_RE.search("Date of Notice: 05/15/2022")
    assert m_notice is not None and "05/15/2022" in m_notice.group(1)

    m_plan = PLAN_ADOPTION_RE.search("Rule 10b5-1 instruction date: 12/01/2021")
    assert m_plan is not None and "12/01/2021" in m_plan.group(1)
