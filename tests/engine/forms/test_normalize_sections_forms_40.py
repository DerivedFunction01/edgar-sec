"""Section resolution for the 40-series form families."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.normalize import normalize_document
from tests.support.fixtures import fixture_path


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "000000223010000054__adxfidelitybond.htm",
            [
                "ITEM DECLARATIONS",
                "ITEM INSURING AGREEMENTS",
                "ITEM GENERAL AGREEMENTS",
            ],
        ),
    ],
)
def test_form_4017g_specimens_resolve_sections(
    fixture: str, expected: list[str]
) -> None:
    """Bond-instrument specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_4017g/{fixture}")
    res = normalize_document(path.read_bytes(), form="40-17G", document_path=path.name)

    assert res.family == "40-17G"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_4017g_letter_resolves_no_sections() -> None:
    """A transmittal letter carries no instrument blocks to resolve."""
    fixture = "000089710104001897__faf044428_40-17g.htm"
    path = fixture_path(f"document/form_4017g/{fixture}")
    res = normalize_document(path.read_bytes(), form="40-17G", document_path=path.name)

    assert res.family == "40-17G"
    assert res.sections is not None
    assert res.sections.sections == ()


def test_form_4017g_paper_stub_resolves_no_sections() -> None:
    """A .paper primary has no body: sections stay honestly absent."""
    fixture = "999999999704025615__9999999997-04-025615.paper"
    path = fixture_path(f"document/form_4017g/{fixture}")
    res = normalize_document(path.read_bytes(), form="40-17G", document_path=path.name)

    assert res.family == "40-17G"
    assert res.sections is None


@pytest.mark.parametrize(
    ("fixture", "form", "expected"),
    [
        (
            "0000912057-00-039288__a40-17f1.txt",
            "40-17F1",
            [
                "ITEM INSTRUCTIONS",
                "ITEM REPORT OF INDEPENDENT ACCOUNTANTS",
                "ITEM MANAGEMENT STATEMENT",
            ],
        ),
        (
            "0001111830-13-000443__stralem_4017f1-0513.htm",
            "40-17F1",
            ["ITEM REPORT OF INDEPENDENT ACCOUNTANTS"],
        ),
    ],
)
def test_form_4017f1_specimens_resolve_sections(
    fixture: str, form: str, expected: list[str]
) -> None:
    """Certificate specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_4017f1/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "40-17F1"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_4017f1_paper_stub_resolves_no_sections() -> None:
    """A .paper primary has no body: sections stay honestly absent."""
    fixture = "9999999997-02-050518__9999999997-02-050518.paper"
    path = fixture_path(f"document/form_4017f1/{fixture}")
    res = normalize_document(path.read_bytes(), form="40-17F1", document_path=path.name)

    assert res.family == "40-17F1"
    assert res.sections is None


@pytest.mark.parametrize(
    ("fixture", "form", "expected"),
    [
        (
            "000119312505058584__d4017f2.htm",
            "40-17F2",
            ["ITEM MANAGEMENT STATEMENT", "ITEM REPORT OF INDEPENDENT ACCOUNTANTS"],
        ),
        (
            "000086939205000161__report.txt",
            "40-17F2",
            ["ITEM REPORT OF INDEPENDENT ACCOUNTANTS"],
        ),
        (
            "0001047469-03-041537__a2125145z40-17f2a.txt",
            "40-17F2/A",
            [
                "ITEM INSTRUCTIONS",
                "ITEM REPORT OF INDEPENDENT ACCOUNTANTS",
                "ITEM MANAGEMENT STATEMENT",
            ],
        ),
    ],
)
def test_form_4017f2_specimens_resolve_sections(
    fixture: str, form: str, expected: list[str]
) -> None:
    """Certificate specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_4017f2/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "40-17F2"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


@pytest.mark.parametrize(
    ("fixture", "form", "expected"),
    [
        (
            "0000899681-11-000293__dreyfus-40appa_081711.htm",
            "40-APP/A",
            [
                "ITEM BACKGROUND",
                "ITEM STATEMENT IN SUPPORT OF RELIEF REQUESTED",
                "ITEM PRECEDENTS",
                "ITEM CONDITIONS",
                "ITEM CONCLUSION",
                "ITEM PROCEDURAL MATTERS",
                "ITEM EXHIBIT INDEX",
                "ITEM VERIFICATION",
            ],
        ),
        (
            "0000051931-14-001181__crmc40-app.htm",
            "40-APP",
            [
                "ITEM INTRODUCTION",
                "ITEM BACKGROUND",
                "ITEM REQUEST FOR ORDER",
                "ITEM STATEMENT IN SUPPORT OF RELIEF REQUESTED",
                "ITEM CONCLUSION",
                "ITEM PROCEDURAL MATTERS",
                "ITEM SIGNATURES",
                "ITEM EXHIBIT INDEX",
            ],
        ),
        (
            "0001193125-14-427194__d823951d40appa.htm",
            "40-APP/A",
            [
                "ITEM INTRODUCTION",
                "ITEM APPLICANTS",
                "ITEM REQUEST FOR ORDER",
                "ITEM STATEMENT IN SUPPORT OF RELIEF REQUESTED",
                "ITEM CONDITIONS",
                "ITEM PROCEDURAL MATTERS",
            ],
        ),
    ],
)
def test_form_40app_specimens_resolve_sections(
    fixture: str, form: str, expected: list[str]
) -> None:
    """Draw specimens resolve the sections their bodies carry."""
    path = fixture_path(f"document/form_40app/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "40-APP"
    assert res.sections is not None
    assert [s.item_identifier for s in res.sections.sections] == expected


def test_form_40app_paper_stub_resolves_no_sections() -> None:
    """A .paper primary has no body: sections stay honestly absent."""
    fixture = "9999999997-02-025153__9999999997-02-025153.paper"
    path = fixture_path(f"document/form_40app/{fixture}")
    res = normalize_document(
        path.read_bytes(), form="40-APP/A", document_path=path.name
    )

    assert res.family == "40-APP"
    assert res.sections is None


@pytest.mark.parametrize(
    ("fixture", "form"),
    [
        ("0000356787-08-000034__e726-728.htm", "40-24B2"),
        ("0000894189-11-003926__rbc_4024b2-a.htm", "40-24B2/A"),
    ],
)
def test_form_4024b2_specimens_resolve_no_sections(fixture: str, form: str) -> None:
    """Sales-literature bodies carry no sections: absence stays honest."""
    path = fixture_path(f"document/form_4024b2/{fixture}")
    res = normalize_document(path.read_bytes(), form=form, document_path=path.name)

    assert res.family == "40-24B2"
    assert res.sections is None
