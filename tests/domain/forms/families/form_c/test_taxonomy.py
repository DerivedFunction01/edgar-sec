from __future__ import annotations

from edgar_sec.domain.forms.families.form_c.models import FormCKind
from edgar_sec.domain.forms.families.form_c.taxonomy import (
    FORMC_SUBMISSION_TYPES,
    FORMC_XML_SPEC,
    kind_of,
)


def test_xml_spec_matches_formc_schema() -> None:
    assert FORMC_XML_SPEC.root_tags == frozenset({"edgarSubmission"})
    assert "http://www.sec.gov/edgar/formc" in FORMC_XML_SPEC.namespaces


def test_kind_dispatch_covers_all_types() -> None:
    assert len(FORMC_SUBMISSION_TYPES) == 10
    for submission_type in FORMC_SUBMISSION_TYPES:
        assert kind_of(submission_type) is not FormCKind.UNKNOWN


def test_kind_dispatch_groups() -> None:
    assert kind_of("C") is FormCKind.OFFERING
    assert kind_of("C/A") is FormCKind.OFFERING
    assert kind_of("C-U") is FormCKind.PROGRESS
    assert kind_of("C-AR/A") is FormCKind.ANNUAL_REPORT
    assert kind_of("C-TR") is FormCKind.TERMINATION
    assert kind_of("C-AR-W") is FormCKind.WITHDRAWAL
    assert kind_of("ZZ") is FormCKind.UNKNOWN
    assert kind_of(None) is FormCKind.UNKNOWN
