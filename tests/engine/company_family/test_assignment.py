"""Family assignment invariants: a sponsor's SPVs form one family, a sponsor's own
entity stays outside it, and unrelated issuers never share a key.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pytest

from edgar_sec.engine.company_family.assignment import (
    assignment_relation_sql,
    build_assignment,
    register_udfs,
)

CORPUS: list[tuple[str, str]] = [
    ("0000019617", "JPMorgan Chase & Co"),
    ("0000019618", "JP MORGAN CHASE & CO"),
    (
        "0001319760",
        "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
    ),
    ("0001319761", "JPMorgan Chase Auto Receivables Trust 2025-1"),
    ("0000895421", "Morgan Stanley"),
    ("0001387224", "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4"),
    ("0001387225", "Morgan Stanley Mortgage Loan Trust 2004-1"),
    ("0001566138", "Honda Auto Receivables 2013-1 Owner Trust"),
    ("0001566139", "Honda Motor Co Ltd"),
    ("0001383094", "Santander Drive Auto Receivables LLC"),
    ("0001398244", "Santander Drive Auto Receivables Trust 2007-2"),
    ("0001570776", "Santander Drive Auto Receivables Trust 2013-2"),
    ("0001600001", "Wells Fargo & Co"),
    ("0001600002", "Wells Fargo Mortgage Backed Securities Trust 2005-1"),
    ("0001600003", "Wells Fargo Alternative Loan Trust 2007-1"),
    ("0000866787", "AutoZone Inc"),
    ("0000866788", "FT 199"),
    ("0000866789", "FT 13398"),
    ("0000900001", "SMARTTRUST 455"),
    ("0000900002", "SMART TRUST 218"),
    ("0000900003", "WOOD MICHAEL"),
    ("0000900004", "WOODS MICHAEL"),
    ("0000900005", "DE-0924 FUND II, A SERIES OF ROLL UP VEHICLES, LP"),
    ("0000900006", "HAN INTO SOMNAIR SEP 2024 A SERIES OF CGF2021 LLC"),
    ("0000900007", "V.I.A. CORP."),
    ("0000900008", "MARYLAND TAX EXEMPT TRUST"),
    ("0000900009", "KANSAS TAX EXEMPT TRUST"),
]


def _rows(corpus: list[tuple[str, str]] = CORPUS) -> dict[str, str]:
    """Assign a corpus and return `cik -> company_family`."""
    con = duckdb.connect()
    values = ", ".join("('%s', '%s')" % (c, n.replace("'", "''")) for c, n in corpus)
    build_assignment(con, f"SELECT * FROM (VALUES {values}) t(cik, name)")
    return dict(
        con.execute("SELECT cik, company_family FROM family_assignment").fetchall()
    )


@pytest.fixture(scope="module")
def families() -> dict[str, str]:
    return _rows()


def test_a_sponsors_spvs_share_one_family_across_product_lines(families) -> None:
    """Auto, mortgage, and loan vehicles are one sponsor's SPVs, not three families."""
    spvs = [families[cik] for cik in ("0001600002", "0001600003")]
    assert len(set(spvs)) == 1
    assert spvs[0].startswith("spv:")


def test_a_sponsor_entity_is_outside_its_own_spv_namespace(families) -> None:
    """The typed key prefix is what stops the two from colliding."""
    assert families["0001600001"].startswith("entity:")
    assert families["0001600002"].startswith("spv:")
    assert families["0001600001"] != families["0001600002"]


def test_an_honda_the_automaker_is_separate_from_its_receivables(families) -> None:
    assert families["0001566139"].startswith("entity:")
    assert families["0001566138"].startswith("spv:")
    assert families["0001566139"] != families["0001566138"]


def test_a_parent_entity_shares_its_spv_family_when_it_is_marked(families) -> None:
    """The rule is marker-driven, so an SPV-marked sponsor title joins the vehicles."""
    keys = {families[c] for c in ("0001383094", "0001398244", "0001570776")}
    assert len(keys) == 1
    assert next(iter(keys)).startswith("spv:")


def test_both_spellings_of_one_institution_resolve_to_one_key(families) -> None:
    assert families["0000019617"] == families["0000019618"]


def test_a_token_split_alone_does_not_split_a_family(families) -> None:
    assert families["0000900001"] == families["0000900002"]
    assert families["0000900001"].startswith("entity:")


def test_surnames_are_not_folded_into_one_person(families) -> None:
    assert families["0000900003"] != families["0000900004"]


def test_an_umbrella_phrase_names_its_parent(families) -> None:
    assert families["0000900005"] == "spv:roll up vehicles"
    assert families["0000900006"] == "spv:cgf2021"


def test_a_name_with_no_identity_is_keyed_by_its_own_cik(families) -> None:
    """Otherwise every unidentifiable registrant shares one meaningless bucket."""
    assert families["0000900007"] == "cik:0000900007"


def test_distinct_tax_exempt_trusts_do_not_collapse(families) -> None:
    assert families["0000900008"] != families["0000900009"]


def test_a_registrant_always_gets_exactly_one_family(families) -> None:
    assert set(families) == {cik for cik, _ in CORPUS}
    assert all(key for key in families.values())


def test_every_family_key_is_namespaced() -> None:
    prefixes = ("entity:", "spv:", "cik:")
    assert all(k.startswith(prefixes) for k in _rows().values())


def test_stats_cover_every_registrant_exactly_once() -> None:
    con = duckdb.connect()
    values = ", ".join("('%s', '%s')" % (c, n) for c, n in CORPUS)
    stats = build_assignment(con, f"SELECT * FROM (VALUES {values}) t(cik, name)")
    assert stats.registrants == len(CORPUS)
    assert stats.entity_families + stats.spv_families + stats.singletons == len(
        set(_rows().values())
    )


def test_assignment_is_deterministic_for_the_same_corpus() -> None:
    assert _rows() == _rows()


def test_a_resolver_is_registered_once_and_is_reusable() -> None:
    con = duckdb.connect()
    register_udfs(con)
    register_udfs(con)
    assert con.execute("SELECT fam_stem('FT 199')").fetchone()[0] == "ft"


def test_the_published_relation_normalizes_cik_padding() -> None:
    sql = assignment_relation_sql("/tmp/family.parquet")
    assert "lpad(" in sql and "company_family" in sql


def test_a_build_never_touches_the_network(tmp_path: Any) -> None:
    """The roster is the only input, so the engine has no source to fetch."""
    con = duckdb.connect()
    values = ", ".join("('%s', '%s')" % (c, n) for c, n in CORPUS[:3])
    build_assignment(con, f"SELECT * FROM (VALUES {values}) t(cik, name)")
    assert con.execute("SELECT count(*) FROM family_assignment").fetchone()[0] == 3
