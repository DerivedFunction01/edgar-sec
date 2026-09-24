"""Contract tests for domain-neutral English grammar and lexical tokens."""

from __future__ import annotations

from defs.text.grammar import (
    ARTICLES,
    FUNCTION_WORDS,
    PROSE_TRANSITION_PHRASES,
    RE_ARTICLE,
    RE_POSSESSIVE,
    RE_PROSE_TRANSITION_PHRASE,
    RE_RELATIVE_PRONOUN,
    RE_TRAILING_CONNECTOR,
    RE_VERBAL_PARTICIPLE,
    RE_WORD_TOKEN,
    RELATIVE_PRONOUNS,
    TRAILING_CONNECTORS,
)


def test_articles_and_pronouns() -> None:
    assert "the" in ARTICLES
    assert "a" in ARTICLES
    assert "an" in ARTICLES
    assert RE_ARTICLE.search("the company") is not None
    assert RE_ARTICLE.search("an asset") is not None
    assert RE_ARTICLE.search("theater") is None  # Word boundary check

    assert "which" in RELATIVE_PRONOUNS
    assert "whereby" in RELATIVE_PRONOUNS
    assert RE_RELATIVE_PRONOUN.search("under which the parties") is not None
    assert RE_RELATIVE_PRONOUN.search("sandwich") is None


def test_function_words() -> None:
    assert len(FUNCTION_WORDS) == 131
    assert "and" in FUNCTION_WORDS
    assert "because" in FUNCTION_WORDS
    assert "between" in FUNCTION_WORDS
    assert "apple" not in FUNCTION_WORDS


def test_trailing_connectors() -> None:
    assert "in" in TRAILING_CONNECTORS
    assert "with" in TRAILING_CONNECTORS
    assert RE_TRAILING_CONNECTOR.search("as set forth in") is not None
    assert RE_TRAILING_CONNECTOR.search("as set forth with   ") is not None
    assert RE_TRAILING_CONNECTOR.search("in the beginning") is None


def test_prose_transition_phrases() -> None:
    assert "in accordance with" in PROSE_TRANSITION_PHRASES
    assert "pursuant to" in PROSE_TRANSITION_PHRASES
    assert (
        RE_PROSE_TRANSITION_PHRASE.search("prepared in accordance with GAAP")
        is not None
    )


def test_possessive_and_participles() -> None:
    assert RE_POSSESSIVE.search("Company's assets") is not None
    assert RE_POSSESSIVE.search("it's") is not None
    assert RE_POSSESSIVE.search("'s") is None  # Too short

    assert RE_VERBAL_PARTICIPLE.search("operating activities") is not None
    assert RE_VERBAL_PARTICIPLE.search("reported earnings") is not None


def test_word_token_pattern() -> None:
    text = "The Company's 10,000 shares (50.5%)"
    tokens = RE_WORD_TOKEN.findall(text)
    assert "The" in tokens
    assert "Company's" in tokens
    assert "10,000" in tokens
    assert "50.5%" in tokens
