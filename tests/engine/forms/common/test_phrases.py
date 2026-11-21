from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseEffect,
    PhraseRule,
)
from edgar_sec.engine.forms.common.phrases import (
    compile_phrase_rules,
    match_phrase_rules,
)


def test_match_phrase_rule_preserves_source_span_and_neighbor_lines():
    source = (
        "Field label\n"
        "Please see\n"
        "Instruction 4(b)(v) before responding.\n"
        "Captured value\n"
    )
    rule = PhraseRule(
        "form144.instruction",
        (("Instruction 4(b)(v)",),),
        PhraseCategory.INSTRUCTION,
        effect=PhraseEffect.BOUNDARY,
        family_ids=frozenset({"form144"}),
        section_roles=frozenset({"instructions"}),
        context_lines=1,
    )

    (match,) = match_phrase_rules(
        source,
        compile_phrase_rules((rule,)),
        family_id="form144",
        section_role="instructions",
        source_id="source-1",
    )

    assert match.matched_text == "Instruction 4(b)(v)"
    assert source[match.start_offset : match.end_offset] == match.matched_text
    assert match.start_line == 3
    assert match.end_line == 3
    assert match.previous_lines == ("Please see",)
    assert match.next_lines == ("Captured value",)
    assert match.source_id == "source-1"
    assert match.effect is PhraseEffect.BOUNDARY


def test_match_phrase_sequence_across_wrapped_text_with_component_offsets():
    source = "Certification\nAfter reasonable inquiry\nand to the best of my knowledge.\nValue"
    rule = PhraseRule(
        "common.certification",
        (("After reasonable inquiry", "to the best of my knowledge"),),
        PhraseCategory.CERTIFICATION,
        max_gap_chars=16,
        context_lines=1,
    )

    (match,) = match_phrase_rules(source, compile_phrase_rules((rule,)))

    assert (
        match.matched_text
        == "After reasonable inquiry\nand to the best of my knowledge"
    )
    assert tuple(source[start:end] for start, end in match.component_spans) == (
        "After reasonable inquiry",
        "to the best of my knowledge",
    )
    assert match.previous_lines == ("Certification",)
    assert match.next_lines == ("Value",)


def test_phrase_rules_respect_family_and_section_scope():
    rule = PhraseRule(
        "ownership.warning",
        (("Federal criminal violations",),),
        PhraseCategory.WARNING,
        family_ids=frozenset({"ownership"}),
        section_roles=frozenset({"signatures"}),
    )
    compiled = compile_phrase_rules((rule,))
    text = "Intentional misstatements constitute federal criminal violations."

    assert not match_phrase_rules(text, compiled, family_id="form144")
    assert not match_phrase_rules(
        text, compiled, family_id="ownership", section_role="body"
    )
    assert match_phrase_rules(
        text, compiled, family_id="ownership", section_role="signatures"
    )


def test_phrase_match_does_not_remove_source_text():
    source = "Warning: see instruction 6 for procedure.\nReported value"
    rule = PhraseRule(
        "statutory.instruction",
        (("see instruction 6 for procedure",),),
        PhraseCategory.INSTRUCTION,
        effect=PhraseEffect.EXCLUDE_FROM_VALUE,
    )
    (match,) = match_phrase_rules(source, compile_phrase_rules((rule,)))

    assert source[match.start_offset : match.end_offset] == match.matched_text
    assert source.endswith("Reported value")
