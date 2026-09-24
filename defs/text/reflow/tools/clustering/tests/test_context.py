"""Unit tests for BlockContext scalar properties and primitive reuse."""

from __future__ import annotations

from defs.text.reflow.registry import FEATURE_REGISTRY
from defs.text.reflow.tools.clustering.context import BlockContext

SAMPLE_PROSE = (
    "The Company's consolidated financial statements have been prepared in accordance\n"
    "with U.S. generally accepted accounting principles. In connection with these\n"
    "principles, management is required to make estimates and assumptions that affect\n"
    "the reported amounts of assets and liabilities as of June 30, 2009."
)

SAMPLE_TABLE = (
    "          Office furniture and equipment  $   191,046\n"
    "          Computer equipment                  127,686\n"
    "          Leasehold improvements               22,559\n"
    "          Tradeshow accessories                55,960\n"
    "                                          -----------\n"
    "                                              397,251\n"
    "          Less accumulated depreciation      (133,812)\n"
    "                                          -----------\n"
    "                                          $   263,439\n"
    "                                          ==========="
)

SAMPLE_CHECKBOX = (
    "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n"
    "[ ] TRANSITION REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934"
)

SAMPLE_FINANCIAL_BRIDGE = (
    "LIABILITIES AND STOCKHOLDERS' EQUITY\n"
    "Current liabilities:\n"
    "    Accounts payable                            $ 45,210"
)


def test_block_context_prose_properties() -> None:
    ctx = BlockContext(SAMPLE_PROSE)
    assert ctx.line_count == 4
    assert ctx.ends_terminal_punct is True
    assert ctx.starts_capital_or_indent is True
    assert ctx.has_table_wrapper_tag is False
    assert ctx.has_checkbox is False
    assert ctx.is_financial_bridge is False
    assert ctx.possessive_count == 1  # "Company's"
    assert ctx.relative_clause_count >= 1  # "that"
    assert ctx.narrative_date_count == 1  # "June 30, 2009"
    assert ctx.soft_wrap_count >= 2
    assert ctx.soft_wrap_ratio >= 0.5
    assert ctx.non_final_ends_numeric is False
    assert ctx.gutter_4_col_count == 0
    assert ctx.has_deadspace_corridor is False


def test_block_context_table_properties() -> None:
    ctx = BlockContext(SAMPLE_TABLE)
    assert ctx.line_count == 10
    assert ctx.gutter_4_col_count >= 2
    assert ctx.column_underline_count >= 2  # "-----------"
    assert ctx.cell_edge_aligned_count >= 2
    assert ctx.soft_wrap_count == 0
    assert ctx.soft_wrap_ratio == 0.0
    assert ctx.possessive_count == 0


def test_block_context_checkbox() -> None:
    ctx = BlockContext(SAMPLE_CHECKBOX)
    assert ctx.has_checkbox is True
    assert ctx.soft_wrap_count == 0


def test_block_context_financial_bridge() -> None:
    ctx = BlockContext(SAMPLE_FINANCIAL_BRIDGE)
    assert ctx.is_financial_bridge is True


def test_feature_serialization() -> None:
    ctx = BlockContext(SAMPLE_PROSE)
    feat_dict = ctx.to_feature_dict()
    assert len(feat_dict) == len(FEATURE_REGISTRY)
    for name in FEATURE_REGISTRY:
        assert name in feat_dict

    vec = ctx.to_feature_vector()
    assert len(vec) == len(FEATURE_REGISTRY)
    assert vec.dtype.kind == "f"
