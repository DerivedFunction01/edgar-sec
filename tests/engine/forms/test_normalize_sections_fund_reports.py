"""Section resolution for fund and report form families."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.normalize import normalize_document
from tests.support.fixtures import fixture_path


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "0001193125-17-066843__d308706d18ka.htm",
            ["ITEM SIGNATURES", "ITEM EXHIBIT INDEX"],
        ),
        (
            "0001104659-26-117215__tm2627716d1_18ka.htm",
            [
                "ITEM EXPLANATORY NOTE",
                "ITEM CAPITALIZATION AND INDEBTEDNESS",
                "ITEM SIGNATURES",
                "ITEM EXHIBIT INDEX",
            ],
        ),
        (
            "0001206212-03-000011__m09206a1e18vkza.txt",
            ["ITEM SIGNATURES", "ITEM EXHIBIT INDEX"],
        ),
    ],
)
def test_form_18k_specimens_resolve_sections(fixture: str, expected: list[str]) -> None:
    """Census specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_18k/{fixture}")
    res = normalize_document(path.read_bytes(), form="18-K/A", document_path=path.name)

    assert res.family == "18-K"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_18k_paper_stub_resolves_no_sections() -> None:
    """A .paper primary has no body: sections stay honestly absent."""
    fixture = "9999999997-02-012414__9999999997-02-012414.paper"
    path = fixture_path(f"document/form_18k/{fixture}")
    res = normalize_document(path.read_bytes(), form="18-K", document_path=path.name)

    assert res.family == "18-K"
    assert res.sections is None


@pytest.mark.parametrize(
    ("fixture", "form"),
    [
        ("0001445546-13-000978__s-6.txt", "S-6"),
        ("0000875626-03-001585__s487.txt", "487"),
    ],
)
def test_form_s6_specimens_resolve_sections(fixture: str, form: str) -> None:
    """S-6 and Rule 487 specimens resolve their prospectus sections."""
    path = fixture_path(f"document/form_s6/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "S-6"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == [
        "ITEM SUMMARY OF ESSENTIAL INFORMATION",
        "ITEM FEE TABLE",
    ]


@pytest.mark.parametrize(
    ("fixture", "form", "expected"),
    [
        (
            "0001086144-00-000101__0001.txt",
            "N-30D",
            [
                "ITEM LETTER TO SHAREHOLDERS",
                "ITEM FUND PERFORMANCE",
                "ITEM STATEMENT OF ASSETS AND LIABILITIES",
                "ITEM STATEMENT OF OPERATIONS",
                "ITEM STATEMENTS OF CHANGES IN NET ASSETS",
                "ITEM FINANCIAL HIGHLIGHTS",
                "ITEM NOTES TO FINANCIAL STATEMENTS",
                "ITEM REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
            ],
        ),
        (
            "0001005477-01-501237__d01-34714.txt",
            "N-30D/A",
            [
                "ITEM LETTER TO SHAREHOLDERS",
                "ITEM STATEMENT OF ASSETS AND LIABILITIES",
                "ITEM STATEMENT OF OPERATIONS",
                "ITEM STATEMENTS OF CHANGES IN NET ASSETS",
                "ITEM FINANCIAL HIGHLIGHTS",
                "ITEM NOTES TO FINANCIAL STATEMENTS",
                "ITEM REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
                "ITEM PORTFOLIO OF INVESTMENTS",
            ],
        ),
        (
            "0000950137-05-013155__c99520a1nv30bv2.htm",
            "N-30B-2",
            [
                "ITEM STATEMENTS OF CHANGES IN NET ASSETS",
                "ITEM FINANCIAL HIGHLIGHTS",
                "ITEM NOTES TO FINANCIAL STATEMENTS",
            ],
        ),
    ],
)
def test_form_n30d_specimens_resolve_sections(
    fixture: str, form: str, expected: list[str]
) -> None:
    """Census specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_n30d/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "N-30D"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_n30d_short_amendment_resolves_no_sections() -> None:
    """A short amendment body carries no report structure."""
    fixture = "0001193125-11-244302__dn30da.htm"
    path = fixture_path(f"document/form_n30d/{fixture}")
    res = normalize_document(path.read_bytes(), form="N-30D/A", document_path=path.name)

    assert res.family == "N-30D"
    assert res.sections is not None
    assert res.sections.sections == ()


def test_form_nvp_specimen_resolves_sections() -> None:
    """A notice document resolves its key-information sections."""
    fixture = "0000806180-21-000025__completenoticedocument.htm"
    path = fixture_path(f"document/form_nvp/{fixture}")
    res = normalize_document(path.read_bytes(), form="N-VP", document_path=path.name)

    assert res.family == "N-VP"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == [
        "ITEM UPDATED INFORMATION",
        "ITEM KEY INFORMATION",
        "ITEM FEES AND EXPENSES",
        "ITEM RISKS",
        "ITEM RESTRICTIONS",
        "ITEM TAXES",
        "ITEM CONFLICTS OF INTEREST",
        "ITEM APPENDIX: PORTFOLIOS AVAILABLE",
    ]


def test_form_nvp_supplement_resolves_no_sections() -> None:
    """A supplement restating no section resolves none, honestly."""
    fixture = "0000912869-26-000009__a2026-04spinnadvzeroasset.htm"
    path = fixture_path(f"document/form_nvp/{fixture}")
    res = normalize_document(path.read_bytes(), form="N-VP/A", document_path=path.name)

    assert res.family == "N-VP"
    assert res.sections is None or not res.sections.sections


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "0000355348-01-000008__0001.txt",
            [
                "ITEM NAME AND ADDRESS OF ISSUER",
                "ITEM FILE NUMBERS",
                "ITEM CALCULATION OF REGISTRATION FEE",
                "ITEM PREPAID SHARES",
                "ITEM SIGNATURES",
            ],
        ),
        (
            "0001386929-21-000001__stockdivtwenty42020.txt",
            [
                "ITEM CALCULATION OF REGISTRATION FEE",
                "ITEM TOTAL AMOUNT DUE",
                "ITEM SIGNATURES",
            ],
        ),
        (
            "0001116679-04-000921__file01.htm",
            [
                "ITEM NAME AND ADDRESS OF ISSUER",
                "ITEM CALCULATION OF REGISTRATION FEE",
                "ITEM SIGNATURES",
            ],
        ),
    ],
)
def test_form_24f2_specimens_resolve_sections(
    fixture: str, expected: list[str]
) -> None:
    """Census specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_24f2/{fixture}")
    res = normalize_document(path.read_bytes(), form="24F-2NT", document_path=path.name)

    assert res.family == "24F-2NT"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


@pytest.mark.parametrize(
    ("fixture", "form"),
    [
        ("0000858581-22-000065__primary_doc.xml", "24F-2NT"),
        ("0000950162-94-000092__24f-2tm.txt", "24F-2TM"),
    ],
)
def test_form_24f2_unheaded_specimens_resolve_no_sections(
    fixture: str, form: str
) -> None:
    """Structured XML and free-form letters carry no caption structure."""
    path = fixture_path(f"document/form_24f2/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "24F-2NT"
    assert res.sections is not None
    assert res.sections.sections == ()


@pytest.mark.parametrize(
    ("fixture", "form", "family", "expected"),
    [
        (
            "0000896717-95-000007__0000896717-95-000007.txt",
            "N-23C-1",
            "N-23C-1",
            ["ITEM PURCHASES STATEMENT"],
        ),
        (
            "000091384909000258__n23c2_032009.htm",
            "N-23C-2",
            "N-23C-2",
            ["ITEM SIGNATURES"],
        ),
        (
            "000110465922098710__tm2225392d1_n23c3a.htm",
            "N-23C3A",
            "N-23C-3",
            [
                "ITEM NOTIFICATION OF REPURCHASE OFFER",
                "ITEM INVESTMENT COMPANY ACT FILE NUMBER",
                "ITEM EXACT NAME OF INVESTMENT COMPANY",
                "ITEM ADDRESS OF PRINCIPAL EXECUTIVE OFFICE",
                "ITEM OFFER TYPE ELECTION",
                "ITEM REPURCHASE REQUEST DEADLINE",
                "ITEM REPURCHASE REQUEST FORM",
                "ITEM PAYMENT AND DELIVERY INSTRUCTIONS",
            ],
        ),
        (
            "0001515001-19-000018__vcmixformn23c3-9132019final.htm",
            "N-23C3C",
            "N-23C-3",
            [
                "ITEM NOTIFICATION OF REPURCHASE OFFER",
                "ITEM INVESTMENT COMPANY ACT FILE NUMBER",
                "ITEM EXACT NAME OF INVESTMENT COMPANY",
                "ITEM ADDRESS OF PRINCIPAL EXECUTIVE OFFICE",
                "ITEM OFFER TYPE ELECTION",
                "ITEM REPURCHASE OFFER TERMS",
            ],
        ),
    ],
)
def test_form_n23c_specimens_resolve_sections(
    fixture: str, form: str, family: str, expected: list[str]
) -> None:
    """Census specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_n23c/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == family
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_n23c_paper_stub_resolves_no_sections() -> None:
    """A .paper primary has no body: sections stay honestly absent."""
    fixture = "9999999997-03-043480__9999999997-03-043480.paper"
    path = fixture_path(f"document/form_n23c/{fixture}")
    res = normalize_document(path.read_bytes(), form="N-23C3B", document_path=path.name)

    assert res.family == "N-23C-3"
    assert res.sections is None
