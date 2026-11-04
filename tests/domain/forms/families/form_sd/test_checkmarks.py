from __future__ import annotations

from edgar_sec.domain.forms.families.form_sd.checkmarks import SD_CHECKBOX_SCHEMA


def test_schema_covers_the_rule_election_pair() -> None:
    keys = [label.key for label in SD_CHECKBOX_SCHEMA.labels]
    assert keys == ["rule_13p_1", "rule_13q_1"]
    assert SD_CHECKBOX_SCHEMA.family == "SD"
