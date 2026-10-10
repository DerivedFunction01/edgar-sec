"""Coercion and alias-resolution helpers.
They are total by contract: invalid input yields `None` or an empty collection and
is reported through an anomaly rather than raised.
"""

from __future__ import annotations

from edgar_sec.domain.identity import Cik
from edgar_sec.engine.submissions import helpers
from edgar_sec.engine.submissions.helpers import (
    accession_normalized,
    add_anomaly,
    build_archive_url,
    normalize_items,
    resolve_alias,
    to_bool,
    to_int,
)


def test_the_public_surface_is_explicit() -> None:
    assert set(helpers.__all__) == {
        "accession_normalized",
        "add_anomaly",
        "build_archive_url",
        "canonical_json",
        "normalize_items",
        "resolve_alias",
        "to_bool",
        "to_int",
    }
    # CIK padding belongs to the validated identity primitive, not a local zero-fill
    # that would accept out-of-range values.
    assert not hasattr(helpers, "normalize_cik_padded")
    assert Cik(37996).to_10digit() == "0000037996"


def test_add_anomaly_uses_the_canonical_record_shape() -> None:
    anomalies: list[dict] = []
    add_anomaly(anomalies, "bad_field", "detail", "source")
    assert anomalies == [{"code": "bad_field", "detail": "detail", "source": "source"}]
    add_anomaly(anomalies, "no_source", "still recorded")
    assert anomalies[1] == {
        "code": "no_source",
        "detail": "still recorded",
        "source": "",
    }


def test_resolve_alias_prefers_the_declared_key_when_present() -> None:
    payload = {"investorWebsite": "https://a.example"}
    canonical, value, conflicting, anomalies = resolve_alias(
        payload, ["investorWebsite"]
    )
    assert canonical == "investorWebsite"
    assert value == "https://a.example"
    assert conflicting is False
    assert anomalies == []


def test_resolve_alias_is_case_insensitive_about_which_key_matched() -> None:
    """Only the declared spelling counts as canonical; a variant is still data."""
    payload = {"investorwebsite": "https://a.example"}
    canonical, value, conflicting, anomalies = resolve_alias(
        payload, ["investorWebsite"]
    )
    assert canonical == "investorwebsite"
    assert value == "https://a.example"
    assert conflicting is False
    assert anomalies == []


def test_resolve_alias_reports_disagreeing_duplicates() -> None:
    """Conflicting aliases are flagged, not silently resolved by sort order."""
    payload = {
        "investorWebsite": "https://a.example",
        "INVESTORWEBSITE": "https://b.example",
    }
    canonical, value, conflicting, anomalies = resolve_alias(
        payload, ["investorWebsite"]
    )
    assert canonical == "investorWebsite"
    assert value == "https://a.example"
    assert conflicting is True
    assert anomalies[0]["code"] == "alias_conflict"
    assert "investorWebsite" in anomalies[0]["detail"]


def test_resolve_alias_falls_back_to_the_first_candidate() -> None:
    canonical, value, conflicting, anomalies = resolve_alias({}, ["phone", "telephone"])
    assert canonical == "phone"
    assert value is None
    assert conflicting is False
    assert anomalies == []


def test_accession_normalized_is_lenient_but_bounded() -> None:
    assert accession_normalized("0000037996-26-000039") == "000003799626000039"
    assert accession_normalized("000003799626000039") == "000003799626000039"
    for bad in (None, "", "not-an-accession", "0000037996-26-00003", "0" * 19):
        assert accession_normalized(bad) is None, bad


def test_build_archive_url_requires_a_usable_accession() -> None:
    url, reason = build_archive_url("0000037996", "not-an-accession", "doc.htm")
    assert url is None
    assert "invalid accession" in reason


def test_build_archive_url_explains_a_missing_primary_document() -> None:
    url, reason = build_archive_url("0000037996", "0000037996-26-000039", None)
    assert url is None
    assert reason == "primary_document_missing"


def test_build_archive_url_flags_stub_documents() -> None:
    url, reason = build_archive_url("0000037996", "0000037996-26-000039", "0001.htm")
    assert url is not None and url.endswith("0001.htm")
    assert reason == "primary_document_stub:0001.htm"


def test_normalize_items_handles_both_eras() -> None:
    """Recent history ships lists; older files ship one comma-joined string."""
    assert normalize_items(["10-K", "8-K"]) == ["10-K", "8-K"]
    assert normalize_items("10-K, 8-K") == ["10-K", "8-K"]
    assert normalize_items("10-K, , 8-K") == ["10-K", "8-K"]
    assert normalize_items(" 10-K , 8-K ") == ["10-K", "8-K"]
    assert normalize_items(None) == []
    assert normalize_items(7) == ["7"]
    # Blank entries are preserved so a positional index still lines up with its
    # source array.
    assert normalize_items(["10-K", "", " 8-K "]) == ["10-K", "", " 8-K "]


def test_to_bool_preserves_none() -> None:
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool("true") is True
    assert to_bool("FALSE") is False
    assert to_bool("") is None
    assert to_bool(None) is None
    assert to_bool("maybe") is None
    assert to_bool(True) is True


def test_to_int_rejects_non_integral_values() -> None:
    assert to_int(7) == 7
    assert to_int(7.9) == 7
    assert to_int("42") == 42
    assert to_int("4.2") is None
    assert to_int(None) is None
    assert to_int(True) is None
    assert to_int("abc") is None
