from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import STATUTORY_CHECKBOX_CONSTRAINTS
from edgar_sec.domain.forms.families.form_40f.checkmarks import (
    FORM_40F_CHECKBOX_SCHEMA,
    FORM_40F_LABELS,
)


def test_form_40f_checkbox_schema_properties() -> None:
    assert FORM_40F_CHECKBOX_SCHEMA.family == "40-F"
    assert FORM_40F_CHECKBOX_SCHEMA.groups == ("filer_status", "statutory_binary")
    for constraint in STATUTORY_CHECKBOX_CONSTRAINTS:
        assert constraint in FORM_40F_CHECKBOX_SCHEMA.constraints


def test_form_40f_election_pair_is_exclusive() -> None:
    names = [c.name for c in FORM_40F_CHECKBOX_SCHEMA.constraints]
    assert names[-1] == "form_40f_election_exclusion"
    constraint = FORM_40F_CHECKBOX_SCHEMA.constraints[-1]
    assert constraint.relation == "not_both"
    assert constraint.left == "section_12_registration"
    assert constraint.right == "section_13a_15d_annual_report"


def test_form_40f_labels() -> None:
    keys = [label.key for label in FORM_40F_LABELS]
    assert keys == [
        "section_12_registration",
        "section_13a_15d_annual_report",
        "furnished_aif",
        "furnished_audited_financial_statements",
        "rule_12g3_2b_furnishing",
    ]
    # The common labels ride along: the cover carries the EGC lines.
    all_keys = [label.key for label in FORM_40F_CHECKBOX_SCHEMA.labels]
    assert "emerging_growth_company" in all_keys
    assert all_keys[-5:] == keys
    for label in FORM_40F_LABELS:
        assert label.phrases
