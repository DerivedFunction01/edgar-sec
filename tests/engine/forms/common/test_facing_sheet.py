"""Tests for the shared registration facing-sheet field extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.common.facing_sheet import (
    facing_sheet_fields,
    registration_document_kind,
)

_COVER = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-1
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
Registration No. 333-287547
NEW FOUND GOLD CORP.
(Exact name of Registrant as specified in its charter)
CALCULATION OF REGISTRATION FEE
CUSIP 87636T100
"""


def test_registration_document_kind_by_form_code() -> None:
    assert registration_document_kind("F-1") == "registration_statement"
    assert registration_document_kind("F-1/A") == "amendment"
    assert registration_document_kind("F-1MEF") == "additional_securities_mef"
    assert registration_document_kind("F-3ASR") == "automatic_shelf_registration"
    assert registration_document_kind("F-3D") == "dividend_reinvestment_plan"
    assert registration_document_kind("F-3DPOS") == "post_effective_amendment"
    assert registration_document_kind("F-4 POS") == "post_effective_amendment"
    assert registration_document_kind("F-4MEF") == "additional_securities_mef"


def test_facing_sheet_fields_extract_the_cover_fields() -> None:
    lines = _COVER.splitlines()
    fields = facing_sheet_fields(_COVER, lines, "F-1")
    assert fields["registration_number"] == "333-287547"
    assert fields["registrant_name"] is not None
    assert "NEW FOUND GOLD" in fields["registrant_name"].upper()
    assert fields["document_kind"] == "registration_statement"
    assert fields["fee_table_present"] is True
    assert fields["cusip"] == "87636T100"


def test_facing_sheet_fields_report_absence_honestly() -> None:
    lines = ["UNITED STATES", "SECURITIES AND EXCHANGE COMMISSION"]
    fields = facing_sheet_fields("", lines, "F-3")
    assert fields["registration_number"] is None
    assert fields["registrant_name"] is None
    assert fields["fee_table_present"] is False
    assert fields["cusip"] is None


def test_registrant_name_accepts_foreign_legal_forms() -> None:
    for name in (
        "UBS AG",
        "GRUPO FINANCIERO GALICIA S.A.",
        "KONINKLIJKE PHILIPS ELECTRONICS N.V.",
    ):
        lines = [
            "FORM F-3",
            "REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933",
            name,
        ]
        fields = facing_sheet_fields("", lines, "F-3")
        assert fields["registrant_name"] is not None, name


def test_registrant_name_accepts_limited_suffix() -> None:
    lines = [
        "FORM F-1",
        "REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933",
        "SHIP FINANCE INTERNATIONAL LIMITED",
        "(Exact name of Registrant as specified in its charter)",
    ]
    fields = facing_sheet_fields("", lines, "F-1")
    assert fields["registrant_name"] is not None
    assert "SHIP FINANCE" in fields["registrant_name"].upper()


def test_registration_number_falls_back_to_body_captions() -> None:
    # Era amendments carry the number only in exhibit-index references.
    lines = ["FORM F-1", "REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933"]
    lines += ["filler"] * 200
    lines.append("Exhibit No. 3.1 to Registration Statement No. 333-74483)")
    fields = facing_sheet_fields("", lines, "F-1/A")
    assert fields["registration_number"] == "333-74483"


def test_blank_printed_registration_number_stays_absent() -> None:
    lines = [
        "AS FILED WITH THE SECURITIES AND EXCHANGE COMMISSION ON AUGUST 7, 2000",
        "REGISTRATION NO. 333- ____",
        "FORM F-1",
    ]
    fields = facing_sheet_fields("", lines, "F-1")
    assert fields["registration_number"] is None
