from edgar_sec.engine.forms.ownership.patterns import (
    is_ownership_boilerplate,
    match_ownership_boilerplate,
)


def test_ownership_boilerplate_match_has_source_span_and_category() -> None:
    text = "Reporting owner\nSee instruction 1(a)\nJane Doe"

    (match,) = match_ownership_boilerplate(text)

    assert match.rule_id == "ownership.prose_boilerplate"
    assert text[match.start_offset : match.end_offset] == "See instruction"
    assert match.start_line == 2
    assert match.previous_lines == ("Reporting owner",)
    assert match.next_lines == ("Jane Doe",)
    assert is_ownership_boilerplate("Securities and Exchange Commission")
    assert not is_ownership_boilerplate("Toronto issuer")
