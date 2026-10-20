import pytest

from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseEffect,
    PhraseRule,
)


def test_phrase_rule_rejects_empty_definition():
    with pytest.raises(ValueError, match="non-empty sequences"):
        PhraseRule("notice", (), PhraseCategory.BOILERPLATE)


def test_phrase_rule_rejects_negative_context():
    with pytest.raises(ValueError, match="non-negative"):
        PhraseRule(
            "notice",
            (("OMB notice",),),
            PhraseCategory.OMB_NOTICE,
            effect=PhraseEffect.ANNOTATE,
            context_lines=-1,
        )
