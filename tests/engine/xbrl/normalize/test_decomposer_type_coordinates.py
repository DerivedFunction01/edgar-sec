"""Decomposer tests: coordinates asserted from declared types."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def _text_rule(taxonomy: DomainTaxonomy):
    from edgar_sec.engine.xbrl.taxonomy.item_types import text_coordinate_rule

    return text_coordinate_rule(taxonomy)


def _declaration(qname: str, item_type: str) -> ConceptDeclaration:
    return ConceptDeclaration(
        concept_qname=qname, name=qname.partition(":")[2], item_type=item_type
    )


def test_text_coordinate_asserted_from_declared_string_type(
    tax: DomainTaxonomy,
) -> None:
    """A string-typed narrative gains the coordinate its name never claims."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:RelatedPartyTransactionDescriptionOfTransaction"
    plain = decompose_concept_expression(qname, lex).atom
    assert "M_TEXT_NODE" not in plain.modifiers
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "xbrli:stringItemType"), _text_rule(tax)
    ).atom
    assert "M_TEXT_NODE" in typed.modifiers
    assert typed.head == plain.head
    assert typed.modifiers == plain.modifiers | {"M_TEXT_NODE"}


def test_text_coordinate_follows_type_not_name(tax: DomainTaxonomy) -> None:
    """A TextBlock name with a numeric declared type gets no coordinate."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:SignificantAccountingPoliciesTextBlock"
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "xbrli:monetaryItemType"), _text_rule(tax)
    ).atom
    assert "M_TEXT_NODE" not in typed.modifiers
    block = decompose_concept_expression(
        qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), _text_rule(tax)
    ).atom
    assert "M_TEXT_NODE" in block.modifiers


def test_text_coordinate_absent_declaration_is_byte_identical(
    tax: DomainTaxonomy,
) -> None:
    """No declaration (or no rule) reproduces today's atoms exactly."""
    lex = tax.token_lexicon
    assert lex is not None
    specimens = (
        "us-gaap:SignificantAccountingPoliciesTextBlock",
        "us-gaap:RelatedPartyTransactionDescriptionOfTransaction",
        "us-gaap:Revenues",
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    )
    for qname in specimens:
        baseline = decompose_concept_expression(qname, lex)
        assert (
            decompose_concept_expression(qname, lex, None, _text_rule(tax)) == baseline
        )
        assert (
            decompose_concept_expression(
                qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), None
            )
            == baseline
        )


def _percent_rule(taxonomy: DomainTaxonomy):
    from edgar_sec.engine.xbrl.taxonomy.item_types import percent_coordinate_rule

    return percent_coordinate_rule(taxonomy)


def test_percent_coordinate_asserted_from_declared_percent_type(
    tax: DomainTaxonomy,
) -> None:
    """A percent-typed extension gains the coordinate from its declared type."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    plain = decompose_concept_expression(qname, lex).atom
    assert "M_PERCENT_TYPED" not in plain.modifiers
    typed = decompose_concept_expression(
        qname,
        lex,
        _declaration(qname, "dtr-types1:percentItemType"),
        percent_rule=_percent_rule(tax),
    ).atom
    assert "M_PERCENT_TYPED" in typed.modifiers
    assert typed.head == plain.head
    assert typed.modifiers == plain.modifiers | {"M_PERCENT_TYPED"}


def test_percent_coordinate_follows_type_not_name(tax: DomainTaxonomy) -> None:
    """A Percentage name with a monetary declared type gets no coordinate."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    typed = decompose_concept_expression(
        qname,
        lex,
        _declaration(qname, "xbrli:monetaryItemType"),
        percent_rule=_percent_rule(tax),
    ).atom
    assert "M_PERCENT_TYPED" not in typed.modifiers
    rate = "us-gaap:OperatingLeaseWeightedAverageDiscountRate"
    rated = decompose_concept_expression(
        rate,
        lex,
        _declaration(rate, "dtr-types:percentItemType"),
        percent_rule=_percent_rule(tax),
    ).atom
    assert "M_PERCENT_TYPED" in rated.modifiers


def test_percent_coordinate_absent_declaration_is_byte_identical(
    tax: DomainTaxonomy,
) -> None:
    """No declaration (or no rule) reproduces today's atoms exactly."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    baseline = decompose_concept_expression(qname, lex)
    assert (
        decompose_concept_expression(qname, lex, None, percent_rule=_percent_rule(tax))
        == baseline
    )
    assert (
        decompose_concept_expression(
            qname, lex, _declaration(qname, "dtr-types:percentItemType"), None
        )
        == baseline
    )


def test_text_coordinate_net_of_headline_only(tax: DomainTaxonomy) -> None:
    """NET_OF: the headline atom gains the coordinate; operands stay name-derived."""
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax"
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), _text_rule(tax)
    )
    assert "M_TEXT_NODE" in typed.atom.modifiers
    assert all("M_TEXT_NODE" not in operand.modifiers for operand in typed.operands)
