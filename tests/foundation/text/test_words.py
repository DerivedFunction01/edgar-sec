"""Pins for the shared word tokenizer's decided semantics."""

import re

import pytest

from edgar_sec.foundation.text.words import word_tokens

_FORMER_CLASSIFY_RE = re.compile(r"[a-z][a-z']+")
_FORMER_LABEL_RE = re.compile(r"[a-z][a-z0-9]*")


def _filtered(tokens: list[str]) -> frozenset[str]:
    return frozenset(token for token in tokens if len(token) >= 3)


@pytest.mark.parametrize(
    "text",
    [
        "The following table presents the components of net revenue.",
        "Pursuant to Rule 13a-15 of the Securities Exchange Act.",
        "Don't include the stockholders' equity section.",
        "The company’s results for the years ended December 31.",
        "Form 10-K for the fiscal year ended June 30, 2024.",
        "Employee 401k and 403b plan contributions in Q3.",
        "Level 3 fair value measurements and transfers.",
    ],
)
def test_word_tokens_match_former_classify_stream(text: str) -> None:
    assert word_tokens(text) == _FORMER_CLASSIFY_RE.findall(text.lower())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("don't", ["don't"]),
        ("stockholders' equity", ["stockholders'", "equity"]),
        ("company’s results", ["company", "results"]),
        ("q3", []),
        ("401k", []),
        ("abc123 restated", ["abc", "restated"]),
        ("a to of i", ["to", "of"]),
        ("form 10-k", ["form"]),
    ],
)
def test_decided_semantics(text: str, expected: list[str]) -> None:
    assert word_tokens(text) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        "pursuant to rule of regulation",
        "the following table presents",
        "summarizes our results of",
    ],
)
def test_measured_prose_phrases_tokenize_to_their_words(phrase: str) -> None:
    assert word_tokens(phrase) == phrase.split()


@pytest.mark.parametrize(
    ("text", "former_label", "shared"),
    [
        ("abc123 restated", {"abc123", "restated"}, {"abc", "restated"}),
        ("don't ask", {"don", "ask"}, {"don't", "ask"}),
        (
            "stockholders' equity",
            {"stockholders", "equity"},
            {"stockholders'", "equity"},
        ),
        ("401k plan", {"plan"}, {"plan"}),
        (
            "total current assets",
            {"total", "current", "assets"},
            {"total", "current", "assets"},
        ),
    ],
)
def test_labeller_stream_deltas_are_exactly_these(
    text: str, former_label: frozenset[str], shared: frozenset[str]
) -> None:
    assert _filtered(_FORMER_LABEL_RE.findall(text.lower())) == former_label
    assert _filtered(word_tokens(text)) == shared
