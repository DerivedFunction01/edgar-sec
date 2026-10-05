"""Unit tests for tokenization and Aho-Corasick MultiPatternAutomaton / LexicalMatcher."""

from edgar_sec.foundation.text.automaton import (
    compile_lexical_matcher,
    tier_confidence,
    tokenize,
)


def test_tokenize_positions_and_folding() -> None:
    text = "Form 10-K Annual Report"
    tokens = tokenize(text)
    assert len(tokens) == 5
    assert [t.surface for t in tokens] == ["Form", "10", "K", "Annual", "Report"]
    assert [t.folded for t in tokens] == ["form", "10", "k", "annual", "report"]
    assert tokens[0].start == 0
    assert tokens[0].end == 4


def test_tier_confidence_calibration() -> None:
    assert tier_confidence(3, 1) == 0.92
    assert tier_confidence(2, 1) == 0.83
    assert tier_confidence(1, 1) == 0.50


def test_lexical_matcher_single_pass() -> None:
    categories = {
        "balance_sheet": [
            "consolidated balance sheets",
            "statement of financial position",
        ],
        "income_statement": [
            "consolidated statements of operations",
            "statement of earnings",
        ],
    }
    matcher = compile_lexical_matcher(categories)

    assert matcher.has_any("The Consolidated Balance Sheets of the Company")
    assert matcher.has_any("Statement of Earnings for the Year")
    assert not matcher.has_any("Item 1A Risk Factors")

    matches = matcher.find_matches(
        "Consolidated Balance Sheets and Statement of Earnings"
    )
    assert len(matches) == 2
    categories_matched = {m.category for m in matches}
    assert categories_matched == {"balance_sheet", "income_statement"}

    res = matcher.classify("Consolidated Balance Sheets as of December 31")
    assert res.category == "balance_sheet"
    assert res.confidence > 0.8


def test_lexical_matcher_exclusions() -> None:
    categories = {
        "annual_report": ["form 10-k", "annual report"],
    }
    exclusions = {
        "annual_report": ["quarterly report", "form 10-q"],
    }
    matcher = compile_lexical_matcher(categories, exclusions=exclusions)

    res = matcher.classify("Form 10-K with quarterly report mention")
    assert res.category is None
