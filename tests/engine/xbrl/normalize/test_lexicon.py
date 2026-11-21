"""Unit tests for TokenLexicon greedy phrase matching and claims."""

import json
from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_lexicon_longest_phrase_matching() -> None:
    """Verify greedy longest-phrase matching over multi-word tokens."""
    entries = (
        LexiconEntry(("research",), "modifier", atom="M_RESEARCH"),
        LexiconEntry(("research", "and", "development"), "modifier", atom="M_RD"),
        LexiconEntry(("expense",), "head", head="H_EXPENSE", claim_class="PRIMARY"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Research", "And", "Development", "Expense")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert matches[0].entry.claim_atom() == "M_RD"
    assert matches[1].entry.claim_atom() == "H_EXPENSE"
    assert residuals == []


def test_lexicon_entry_carries_derivation_declaration() -> None:
    """A temporal pattern declared in data loads onto the entry, defaulting to None."""
    entry = LexiconEntry.from_dict(
        {
            "phrase": ["Due", "In"],
            "claim": "modifier",
            "atom": "M_MATURITY",
            "temporal_pattern": "due_in_window",
        }
    )
    assert entry.temporal_pattern == "due_in_window"
    plain = LexiconEntry.from_dict({"phrase": ["Due"], "claim": "modifier"})
    assert plain.temporal_pattern is None


def test_lexicon_residuals_extraction() -> None:
    """Verify unmatched tokens are returned as residuals."""
    entries = (
        LexiconEntry(("revenue",), "head", head="H_REVENUE", claim_class="PRIMARY"),
        LexiconEntry(("net",), "modifier", atom="V_NET"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Foo", "Bar", "Revenue", "Net")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert residuals == ["Foo", "Bar"]


def test_head_claim_without_class_is_a_loader_error() -> None:
    """RR5: a head claim with no class, or an unknown claim kind, is refused."""
    with pytest.raises(ValueError):
        LexiconEntry.from_dict(
            {"phrase": ["Expense"], "claim": "head", "head": "H_EXPENSE"}
        )
    with pytest.raises(ValueError):
        LexiconEntry.from_dict({"phrase": ["Of"], "claim": "subordinator"})


def test_requires_evidence_claim_loads() -> None:
    """Q6 slot: an evidence-gated claim parses onto the entry."""
    entry = LexiconEntry.from_dict(
        {
            "phrase": ["Impairment"],
            "claim": "head",
            "head": "H_EXPENSE",
            "claim_class": "PRIMARY",
            "requires_evidence": True,
        }
    )
    assert entry.requires_evidence is True


def test_grammatical_frame_record_parses_act_modifier() -> None:
    """An act-declaring frame record loads its act modifier; others None."""
    from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

    frame = GrammaticalFrame.from_dict(
        {
            "frame_id": "FRAME_OUTFLOW_PURCHASE",
            "prefix_tokens": ["purchase"],
            "direction": -1.0,
            "strip_tokens": ["to", "for", "of", "and"],
            "act_modifier": "M_PURCHASE",
        }
    )
    assert frame.act_modifier == "M_PURCHASE"
    plain = GrammaticalFrame.from_dict(
        {"frame_id": "FRAME_INFLOW_PROCEEDS_FROM", "prefix_tokens": ["proceeds"]}
    )
    assert plain.act_modifier is None


def test_lexicon_frame_attachment_and_matching() -> None:
    """Attached frames match on leading tokens, in declaration order."""
    from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

    lex = TokenLexicon(())
    assert lex.match_grammatical_frame(("Purchase", "Of", "Assets")) is None
    lex.attach_grammatical_frames(
        (
            GrammaticalFrame("FRAME_A", ("payments", "to"), direction=-1.0),
            GrammaticalFrame(
                "FRAME_B", ("purchase",), direction=-1.0, act_modifier="M_PURCHASE"
            ),
        )
    )
    found = lex.match_grammatical_frame(("Purchase", "Of", "Assets"))
    assert found is not None and found.frame_id == "FRAME_B"
    assert lex.match_grammatical_frame(("Sale", "Of", "Assets")) is None


def test_loaded_taxonomy_attaches_purchase_frames_to_lexicon(
    tax: DomainTaxonomy,
) -> None:
    """The shipped purchase frames reach the lexicon with their act."""
    assert tax.token_lexicon is not None
    frame = tax.token_lexicon.match_grammatical_frame(("Purchases", "Of", "Debt"))
    assert frame is not None
    assert frame.act_modifier == "M_PURCHASE"
    assert frame.direction == -1.0


def test_loaded_lexicon_wordform_twins_share_payloads(tax: DomainTaxonomy) -> None:
    """Each completed word form carries its wired twin's claim payload."""
    assert tax.token_lexicon is not None
    by_phrase = {entry.phrase: entry for entry in tax.token_lexicon.entries}

    def payload(phrase: tuple[str, ...]) -> tuple:
        entry = by_phrase[phrase]
        return (
            entry.claim,
            entry.head,
            entry.claim_class,
            entry.carriage,
            entry.atom,
            entry.direction,
        )

    twins = (
        (("issuance",), ("issuances",)),
        (("settlement",), ("settlements",)),
        (("distribution",), ("distributions",)),
        (("transfer",), ("transfers",)),
        (("transfer", "into"), ("transfers", "into")),
        (("transfer", "out", "of"), ("transfers", "out", "of")),
        (("transfer", "out"), ("transfers", "out")),
        (("deferral",), ("deferred",)),
        (("deferrals",), ("deferred",)),
        (("accrual",), ("accruals",)),
        (("impaired",), ("impairment",)),
        (("amortisation",), ("amortization",)),
        (("availableforsale",), ("available", "for", "sale")),
    )
    for completed, wired in twins:
        assert payload(completed) == payload(wired), completed

    borrowing = by_phrase[("borrowing",)]
    borrowings = by_phrase[("borrowings",)]
    assert payload(("borrowing",)) == payload(("borrowings",))
    assert borrowing.scope_next == ("under", "from")
    assert borrowings.scope_next == ()

    repayment = by_phrase[("repayment",)]
    repayments = by_phrase[("repayments",)]
    assert payload(("repayment",)) == payload(("repayments",))
    assert repayment.scope_next == ("of",)
    assert repayments.scope_next == ()


def test_inflection_expansion_generates_surface_twins(tmp_path: Path) -> None:
    """Canonical-only authored data loads every declared surface form."""
    lexicon_path = tmp_path / "token_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            [
                {
                    "phrase": ["Bond"],
                    "claim": "head",
                    "head": "H_LIABILITY",
                    "claim_class": "PRIMARY",
                    "carriage": ["M_DEBT"],
                },
                {
                    "phrase": ["Repayment"],
                    "claim": "head",
                    "head": "H_CASH",
                    "claim_class": "PRIMARY",
                    "scope_next": ["Of"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "inflections.json").write_text(
        json.dumps(
            {
                "forms": {
                    "bond": ["bond", "bonds"],
                    "repayment": ["repayment", "repayments"],
                },
                "overrides": {
                    "repayment": {"scope_next": ["Of"]},
                    "repayments": {"scope_next": []},
                },
            }
        ),
        encoding="utf-8",
    )
    lex = TokenLexicon.load_json(lexicon_path)
    by_phrase = {entry.phrase: entry for entry in lex.entries}
    assert by_phrase[("bonds",)].head == "H_LIABILITY"
    assert by_phrase[("bonds",)].carriage == ("M_DEBT",)
    assert by_phrase[("repayment",)].scope_next == ("of",)
    assert by_phrase[("repayments",)].scope_next == ()


def test_inflection_expansion_refuses_authored_conflict(tmp_path: Path) -> None:
    """A generated surface authored with another payload is a loader error."""
    lexicon_path = tmp_path / "token_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            [
                {
                    "phrase": ["Repayment"],
                    "claim": "head",
                    "head": "H_CASH",
                    "claim_class": "PRIMARY",
                    "scope_next": ["Of"],
                },
                {
                    "phrase": ["Repayments"],
                    "claim": "head",
                    "head": "H_CASH",
                    "claim_class": "PRIMARY",
                    "scope_next": ["From"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "inflections.json").write_text(
        json.dumps(
            {
                "forms": {"repayment": ["repayment", "repayments"]},
                "overrides": {
                    "repayment": {"scope_next": ["Of"]},
                    "repayments": {"scope_next": []},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        TokenLexicon.load_json(lexicon_path)


def test_loaded_lexicon_expansion_never_loses_authored_entries(
    tax: DomainTaxonomy,
) -> None:
    """Every authored entry survives expansion; gains are generated twins."""
    from collections import Counter

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

    paths = resolve_xbrl_paths()
    raw = json.loads(paths.default_token_lexicon_path.read_text(encoding="utf-8"))
    authored = Counter(LexiconEntry.from_dict(item) for item in raw)
    assert tax.token_lexicon is not None
    expanded = Counter(tax.token_lexicon.entries)
    assert authored - expanded == Counter()
    by_phrase = {entry.phrase: entry for entry in tax.token_lexicon.entries}
    loan_payable = by_phrase[("loan", "payable")]
    assert loan_payable.head == "H_LIABILITY"
    assert loan_payable.carriage == ("M_DEBT",)
    loans_payable = by_phrase[("loans", "payable")]
    assert loans_payable.head == "H_LIABILITY"
    assert loans_payable.carriage == ("M_DEBT",)
    note = by_phrase[("note",)]
    assert note.head == "H_LIABILITY"
    assert note.carriage == ("M_DEBT",)
    assert note.scope_next == ("payable", "payables", "issued")
    assert by_phrase[("notes",)].scope_next == ("payable", "payables", "issued")
    assert ("note", "payable") not in by_phrase
    assert by_phrase[("note", "receivable")].head == "H_ASSET"
    assert ("payment",) in by_phrase and ("payments",) in by_phrase
    assert ("employees",) in by_phrase and ("employee",) not in by_phrase
    assert ("equipment", "disposals") in by_phrase
    assert ("equipment", "disposal") not in by_phrase
    assert ("income", "tax") in by_phrase and ("income", "taxes") not in by_phrase
    assert ("collection",) in by_phrase and ("collections",) not in by_phrase
    assert ("number", "of", "employees") in by_phrase
    assert ("number", "of", "employee") not in by_phrase
    assert ("purchase",) not in by_phrase and ("purchases",) in by_phrase


def test_loaded_lexicon_rp_partner_admissions(tax: DomainTaxonomy) -> None:
    """R/P partner admissions and the one deliberate absence are pinned."""
    assert tax.token_lexicon is not None
    by_phrase = {entry.phrase: entry for entry in tax.token_lexicon.entries}
    other = by_phrase[("other",)]
    assert other.claim == "modifier" and other.atom == "M_OTHER"
    assert ("others",) not in by_phrase
    trade_rec = by_phrase[("trade", "receivable")]
    assert trade_rec.head == "H_ASSET" and trade_rec.carriage == ("M_RECEIVABLE",)
    assert by_phrase[("trade", "receivables")].carriage == ("M_RECEIVABLE",)
    trade_pay = by_phrase[("trade", "payable")]
    assert trade_pay.head == "H_LIABILITY"
    assert trade_pay.carriage == ("M_ACCOUNTS_PAYABLE",)
    assert by_phrase[("trade", "payables")].carriage == ("M_ACCOUNTS_PAYABLE",)
    fin_rec = by_phrase[("finance", "receivable")]
    assert fin_rec.head == "H_ASSET"
    assert fin_rec.carriage == ("M_FINANCING_RECEIVABLE",)
    assert by_phrase[("finance", "receivables")].carriage == ("M_FINANCING_RECEIVABLE",)
    fee_pay = by_phrase[("fee", "payable")]
    assert fee_pay.head == "H_LIABILITY" and fee_pay.carriage == ()
    assert by_phrase[("fees", "payables")].head == "H_LIABILITY"
    assert by_phrase[("fee", "receivables")].carriage == ("M_RECEIVABLE",)
    assert by_phrase[("installments", "payable")].head == "H_LIABILITY"
    assert by_phrase[("installment", "receivables")].carriage == ("M_RECEIVABLE",)
    assert by_phrase[("amounts", "receivable")].carriage == ("M_RECEIVABLE",)
    assert by_phrase[("amount", "payables")].head == "H_LIABILITY"
    notional = by_phrase[("notional", "amounts")]
    assert notional.head == "H_COMMITMENT"
    assert notional.carriage == ("M_NOTIONAL_AMOUNT",)
    assert by_phrase[("carrying", "amounts")].atom == "M_CARRYING_AMOUNT"


def test_coordination_relation_kind_loads() -> None:
    """The COORDINATION relation kind parses; unknown kinds are refused."""
    entry = LexiconEntry.from_dict(
        {"phrase": ["And"], "claim": "relation", "relation": "COORDINATION"}
    )
    assert entry.relation == "COORDINATION"
    assert entry.payload_mods() == ()
    with pytest.raises(ValueError):
        LexiconEntry.from_dict(
            {"phrase": ["And"], "claim": "relation", "relation": "BESIDE"}
        )


def test_loaded_lexicon_carries_and_coordination_entry(tax: DomainTaxonomy) -> None:
    """The loaded lexicon carries exactly one bare `and` coordination entry."""
    assert tax.token_lexicon is not None
    matches = [entry for entry in tax.token_lexicon.entries if entry.phrase == ("and",)]
    assert len(matches) == 1
    assert matches[0].claim == "relation"
    assert matches[0].relation == "COORDINATION"


def test_inflection_verbatim_phrase_loads_ungenerated(tmp_path: Path) -> None:
    """A verbatim phrase generates no twins; its other forms stay absent."""
    lexicon_path = tmp_path / "token_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            [
                {
                    "phrase": ["Sale", "Of", "Properties"],
                    "claim": "modifier",
                    "atom": "M_DISPOSAL_GAIN",
                },
                {
                    "phrase": ["Property"],
                    "claim": "head",
                    "head": "H_ASSET",
                    "claim_class": "PRIMARY",
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "inflections.json").write_text(
        json.dumps(
            {
                "forms": {"property": ["property", "properties"]},
                "verbatim": [["sale", "of", "properties"]],
            }
        ),
        encoding="utf-8",
    )
    lex = TokenLexicon.load_json(lexicon_path)
    phrases = {entry.phrase for entry in lex.entries}
    assert ("sale", "of", "properties") in phrases
    assert ("sale", "of", "property") not in phrases
    assert ("properties",) in phrases


def test_grammatical_frame_record_parses_head() -> None:
    """A head-declaring frame record loads its head; others None."""
    from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

    frame = GrammaticalFrame.from_dict(
        {
            "frame_id": "FRAME_INFLOW_PROCEEDS_FROM",
            "prefix_tokens": ["proceeds", "from"],
            "head": "H_CASH",
        }
    )
    assert frame.head == "H_CASH"
    plain = GrammaticalFrame.from_dict(
        {"frame_id": "FRAME_OUTFLOW_PURCHASE", "prefix_tokens": ["purchase"]}
    )
    assert plain.head is None


def test_loaded_taxonomy_attaches_proceeds_frames_with_heads(
    tax: DomainTaxonomy,
) -> None:
    """The shipped proceeds frames reach the lexicon with H_CASH declared."""
    assert tax.token_lexicon is not None
    led = tax.token_lexicon.match_grammatical_frame(("Proceeds", "From", "Borrowings"))
    assert led is not None
    assert led.frame_id == "FRAME_INFLOW_PROCEEDS_FROM"
    assert led.head == "H_CASH"
    elided = tax.token_lexicon.match_grammatical_frame(
        ("Proceeds", "Accounts", "Receivable")
    )
    assert elided is not None
    assert elided.frame_id == "FRAME_INFLOW_PROCEEDS"
    assert elided.head == "H_CASH"


def test_inflection_override_applies_and_validates(tmp_path: Path) -> None:
    """An override lands as field values; an invalid one stays a loader error."""
    lexicon_path = tmp_path / "token_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            [
                {
                    "phrase": ["Commercial", "Paper"],
                    "claim": "head",
                    "head": "H_LIABILITY",
                    "claim_class": "PRIMARY",
                }
            ]
        ),
        encoding="utf-8",
    )
    inflections_path = tmp_path / "inflections.json"
    inflections_path.write_text(
        json.dumps(
            {
                "forms": {"paper": ["paper", "papers"]},
                "overrides": {"commercial papers": {"claim_class": "TAIL"}},
            }
        ),
        encoding="utf-8",
    )
    lex = TokenLexicon.load_json(lexicon_path)
    by_phrase = {entry.phrase: entry for entry in lex.entries}
    assert by_phrase[("commercial", "papers")].claim_class == "TAIL"
    assert by_phrase[("commercial", "paper")].claim_class == "PRIMARY"
    inflections_path.write_text(
        json.dumps(
            {
                "forms": {"paper": ["paper", "papers"]},
                "overrides": {"commercial papers": {"claim_class": "BOGUS"}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must declare a claim class"):
        TokenLexicon.load_json(lexicon_path)
