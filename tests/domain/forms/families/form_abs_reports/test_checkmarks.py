from __future__ import annotations

from edgar_sec.domain.forms.families.form_abs_reports.checkmarks import (
    ABS_15G_CHECKBOX_LABELS,
    ABS_REPORTS_CHECKBOX_SCHEMA,
)


def test_abs_15g_labels_cover_obligation_pair_and_no_activity_marks() -> None:
    keys = [label.key for label in ABS_15G_CHECKBOX_LABELS]
    assert keys == [
        "rule_15ga_1",
        "rule_15ga_2",
        "no_activity_initial",
        "no_activity_quarterly",
        "no_activity_annual",
    ]


def test_schema_is_registered_for_the_canonical_abs_family() -> None:
    assert ABS_REPORTS_CHECKBOX_SCHEMA.family == "ABS"
    keys = {label.key for label in ABS_REPORTS_CHECKBOX_SCHEMA.labels}
    assert "compliant_12_months" in keys
    assert "rule_15ga_2" in keys
