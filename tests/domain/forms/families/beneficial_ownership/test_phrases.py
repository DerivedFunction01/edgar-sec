from edgar_sec.domain.forms.families.beneficial_ownership.phrases import (
    BENEFICIAL_OWNERSHIP_PHRASE_RULES,
    COVER_LABEL_LEAK_PHRASES,
    PARSED_FIELD_BOILERPLATE_PHRASES,
)


def test_beneficial_ownership_phrase_rules_own_family_vocabularies() -> None:
    rules = {rule.rule_id: rule for rule in BENEFICIAL_OWNERSHIP_PHRASE_RULES}

    assert set(rules) == {
        "beneficial_ownership.cover_label_leak",
        "beneficial_ownership.parsed_field_boilerplate",
    }
    assert rules["beneficial_ownership.cover_label_leak"].family_ids == frozenset(
        {"beneficial_ownership"}
    )
    assert {
        part
        for sequence in rules["beneficial_ownership.cover_label_leak"].sequences
        for part in sequence
    } == set(COVER_LABEL_LEAK_PHRASES)
    assert {
        part
        for sequence in rules["beneficial_ownership.parsed_field_boilerplate"].sequences
        for part in sequence
    } == set(PARSED_FIELD_BOILERPLATE_PHRASES)
