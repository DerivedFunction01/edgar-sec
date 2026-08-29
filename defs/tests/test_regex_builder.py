"""Unit and contract tests for defs.regex builder, trie compaction, and formatting."""

from __future__ import annotations

import re
from enum import Enum

from defs.regex import (
    add_restrictions,
    build_alternation,
    build_compound,
    build_regex,
    compact_alternation,
    plural,
    to_list,
    to_verbose_pattern,
)


class InstrumentEnum(Enum):
    SWAP = "swap"
    OPTION = "option"
    FORWARD = "forward"


def test_to_list_flattens_nested_structures() -> None:
    nested = [
        "a",
        ("b", "c"),
        [InstrumentEnum.SWAP, {InstrumentEnum.OPTION, "d"}],
        None,
    ]
    result = to_list(nested)
    assert "a" in result
    assert "b" in result
    assert "c" in result
    assert "swap" in result
    assert "option" in result
    assert "d" in result
    assert None not in result


def test_build_alternation_sorts_longest_first() -> None:
    terms = ["swap", "interest rate swap", "swap agreement"]
    pattern = build_alternation(terms, sort_longest_first=True)
    assert pattern == "(?:interest rate swap|swap agreement|swap)"

    # Verify matching behavior prefers longest match
    rx = re.compile(pattern)
    m = rx.search("We entered into an interest rate swap agreement")
    assert m is not None
    assert m.group(0) == "interest rate swap"


def test_build_alternation_nested_structures() -> None:
    nested = [
        "swap",
        ["interest rate swap", "currency swap"],
        ("credit default swap", InstrumentEnum.OPTION),
    ]
    pattern = build_alternation(nested)
    assert pattern.startswith("(?:")
    assert "interest rate swap" in pattern
    assert "currency swap" in pattern
    assert "credit default swap" in pattern
    assert "option" in pattern
    assert "swap" in pattern


def test_trie_compaction_matches_exact_terms() -> None:
    terms = ["swap", "swap agreement", "swap option", "swaption"]
    compact = compact_alternation(terms)
    rx = re.compile(f"^{compact}$")

    for t in terms:
        assert rx.match(t) is not None

    assert rx.match("swap invalid") is None
    assert rx.match("other") is None


def test_add_restrictions_lookaround_safety() -> None:
    # Multiple lookbehinds of varying character length
    # In standard re, combining these in a single alternation causes a fixed-width error.
    # add_restrictions must split them into independent lookbehind assertions.
    lookbehinds = ["total", "subtotal", "net"]
    lookaheads = ["rate", "index", "ratio"]

    pattern = add_restrictions(
        base="swap",
        lookbehinds=lookbehinds,
        lookaheads=lookaheads,
    )

    # Must compile cleanly in Python re
    rx = re.compile(pattern)

    # Valid matches: not preceded by 'total ', 'subtotal ', 'net ' and not followed by ' rate', ' index', ' ratio'
    assert rx.search("interest swap agreement") is not None
    assert rx.search("total-swap agreement") is None
    assert rx.search("subtotal-swap agreement") is None
    assert rx.search("net-swap agreement") is None
    assert rx.search("swap-rate agreement") is None
    assert rx.search("swap-ratio agreement") is None


def test_build_compound() -> None:
    prefixes = ["fixed", "floating", "credit"]
    cores = [InstrumentEnum.SWAP, "forward"]
    suffixes = ["agreement", "contract"]

    pattern = build_compound(prefixes, cores, suffixes)
    rx = re.compile(rf"\b{pattern}\b", re.IGNORECASE)

    assert rx.search("fixed-swap-agreement") is not None
    assert rx.search("floating forward contract") is not None
    assert rx.search("credit swap contract") is not None
    assert rx.search("equity note") is None


def test_build_regex_word_boundaries() -> None:
    rx = build_regex(["drop", "alter", "delete"])
    assert rx.search("please drop table x") is not None
    assert rx.search("droplet size is large") is None


def test_to_verbose_pattern() -> None:
    pattern = "(?:first term|second term|third term)"
    verbose = to_verbose_pattern(pattern, comment="Key Terms")
    assert "# Key Terms" in verbose
    assert r"first\ term" in verbose
    assert r"second\ term" in verbose
    assert r"third\ term" in verbose

    rx = re.compile(verbose, re.VERBOSE)
    assert rx.search("second term") is not None


def test_plural_helper() -> None:
    assert plural("mortgage?") == "mortgage"
    assert plural("loans") == "loans"
    assert plural(InstrumentEnum.SWAP) == "swap"


def test_comprehensive_fx_derivative_pattern_generation() -> None:
    """Comprehensive test validating complex nested FX derivative pattern assembly."""
    # 1. Restricted terms
    currency_term = add_restrictions(
        "currency",
        lookbehinds=["single", "crypto", "digital", "virtual"],
    )
    exchange_term = add_restrictions("exchange", lookbehinds=["interest"])

    # 2. Dynamic prefix patterns with nested alternations
    word1 = build_alternation(
        ["forward", "foreign", "currency"], sort_longest_first=True
    )
    compound = build_alternation(
        [
            r"(?:cross|multi)[- ]currency(?:\s+interest[- ]rate)?",
            rf"(?:{exchange_term}|{currency_term})[- ]rate",
        ],
        sort_longest_first=True,
    )
    word2_alt = build_alternation(
        [
            rf"{exchange_term}(?:[- ]rate)?",
            rf"{currency_term}(?:[- ]rate)?",
        ],
        sort_longest_first=True,
    )

    fx_prefixes = [
        rf"(?:{word1})[- ](?:{word1})[- ](?:{word1})[- ](?:{word2_alt})",
        rf"(?:{word1})[- ](?:{word1})[- ](?:{compound})[- ](?:{word2_alt})",
        rf"(?:{word1})[- ](?:{word1})[- ](?:{word2_alt})",
        rf"(?:{word1})[- ](?:{word2_alt})",
        rf"(?:{compound})[- ](?:{word2_alt})",
        rf"(?:{word2_alt})[- ](?:{word2_alt})",
        rf"(?:{compound})",
        r"FX",
        r"forex",
        add_restrictions(r"forward[- ]rates?", lookaheads=[r"agreements?"]),
    ]

    currency_descriptors = build_alternation(
        ["US dollar", "euro", "yen", "pound sterling"], sort_longest_first=True
    )
    forward_types = ["non[- ]deliverable", "deal[- ]contingent"]

    # 3. Bases & Suffixes
    bases = [
        r"derivative contracts?",
        r"forward contracts?",
        r"forward",
        r"option",
        r"swap agreements?",
        r"swap",
        r"contracts?",
        r"agreements?",
    ]
    double_base = r"(?:caps?\s+(?:and|&)\s+floors?|collars?)"

    # Fixed phrases with complex lookarounds
    fixed_phrases = [
        r"(?<!to\s)hedges?\s+of\s+(?:the\s+)?net\s+investments?(?!\s+(?:in|for|to))",
        r"net\s+investment\s+hedges?",
    ]

    # 4. Assemble derivative patterns
    fwd_pattern = build_compound(
        prefix=forward_types, core=["forward", "option", "swap"]
    )
    curr_name_pattern = build_compound(
        prefix=[currency_descriptors], core=["option", "forward", "swap"]
    )
    strict_main = build_compound(prefix=fx_prefixes, core=bases)
    multi_base_pattern = build_compound(
        prefix=fx_prefixes + [currency_term], core=[double_base]
    )

    # Compile strict FX regex
    strict_fx_rx = build_regex(
        [
            strict_main,
            multi_base_pattern,
            curr_name_pattern,
            fwd_pattern,
        ]
        + fixed_phrases,
        use_sep=True,
        flags=re.IGNORECASE,
    )

    # Positive match assertions (must capture the exact full longest match - Max Munch)
    m1 = strict_fx_rx.search(
        "entered into a forward foreign currency exchange rate derivative contract with bank"
    )
    assert m1 is not None
    assert (
        m1.group(0).lower()
        == "forward foreign currency exchange rate derivative contract"
    )

    m2 = strict_fx_rx.search(
        "uses cross-currency interest-rate swap agreements for liability hedging"
    )
    assert m2 is not None
    assert m2.group(0).lower() == "cross-currency interest-rate swap agreements"

    m3 = strict_fx_rx.search("entered into a foreign exchange forward contract")
    assert m3 is not None
    assert m3.group(0).lower() == "foreign exchange forward contract"

    m4 = strict_fx_rx.search("held a non-deliverable forward position")
    assert m4 is not None
    assert m4.group(0).lower() == "non-deliverable forward"

    m5 = strict_fx_rx.search("portfolio of net investment hedges")
    assert m5 is not None
    assert m5.group(0).lower() == "net investment hedges"

    m6 = strict_fx_rx.search("designated hedges of net investments as effective")
    assert m6 is not None
    assert m6.group(0).lower() == "hedges of net investments"

    m7 = strict_fx_rx.search("purchased an FX option contract")
    assert m7 is not None
    assert m7.group(0).lower() == "fx option"

    m8 = strict_fx_rx.search("traded forex swap agreement yesterday")
    assert m8 is not None
    assert m8.group(0).lower() == "forex swap agreement"

    m9 = strict_fx_rx.search("held euro option contracts in Q3")
    assert m9 is not None
    assert m9.group(0).lower() == "euro option"

    m10 = strict_fx_rx.search("foreign currency caps and floors")
    assert m10 is not None
    assert m10.group(0).lower() == "foreign currency caps and floors"

    # Negative / Lookaround protection assertions
    # 1. crypto / digital currency should not match currency term lookbehind
    assert strict_fx_rx.search("bought crypto currency swap") is None
    assert strict_fx_rx.search("digital currency option") is None
    # 2. interest exchange should not match exchange term lookbehind
    assert strict_fx_rx.search("interest exchange contract") is None
    # 3. forward rate agreement lookahead exclusion
    assert strict_fx_rx.search("forward rate agreement") is None
    # 4. net investment hedge lookahead exclusion (followed by 'in' / 'for' / 'to')
    assert (
        strict_fx_rx.search("hedges of net investments in foreign operations") is None
    )
