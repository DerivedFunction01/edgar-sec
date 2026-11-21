from __future__ import annotations

from edgar_sec.pipelines.document_planning.matching import catalog_only_rows
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

from tests.pipelines.document_planning.matching.matching_support import (
    _ACCESSION,
    _ARCHIVE_ROOT,
    _dated_scope,
    _primary_target,
    _scope,
)


def test_no_primary_ge2000_gated_constructs_sequence_one_bundle() -> None:
    rows = catalog_only_rows(
        "plan-1",
        _dated_scope("4", "2024-03-01"),
        (_primary_target("exact_form_with_lazy_index"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "bundle_sequence"
    assert rows[0]["sequence"] == 1
    assert rows[0]["target_url"] == f"{_ARCHIVE_ROOT}/{_ACCESSION}.txt"
    assert rows[0]["status_reason"] == "sgml_bundle_sequence1_ge2000"


def test_no_primary_ge2000_ungated_stays_unresolved() -> None:
    for selection in ("submitted_primary", None):
        rows = catalog_only_rows(
            "plan-1",
            _dated_scope("4", "2024-03-01"),
            (_primary_target(selection),),
        )

        assert rows[0]["status"] == "unresolved"
        assert rows[0]["target_url"] is None
        assert rows[0]["status_reason"] == "no_usable_primary_path"


def test_no_primary_ge2000_non_lazy_family_stays_unresolved() -> None:
    rows = catalog_only_rows(
        "plan-1",
        _dated_scope("6-K", "2024-03-01"),
        (_primary_target("exact_form_with_lazy_index"),),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["status_reason"] == "no_usable_primary_path"


def test_no_primary_pre2000_constructs_bundle_scan() -> None:
    for selection in ("exact_form_with_lazy_index", "submitted_primary", None):
        rows = catalog_only_rows(
            "plan-1",
            _dated_scope("4", "1999-06-01"),
            (_primary_target(selection),),
        )

        assert rows[0]["status"] == "matched"
        assert rows[0]["retrieval_mode"] == "bundle_scan"
        assert rows[0]["sequence"] is None
        assert rows[0]["target_url"] == f"{_ARCHIVE_ROOT}/{_ACCESSION}.txt"
        assert rows[0]["status_reason"] == "sgml_bundle_scan_pre2000"


def test_cohort_split_uses_filing_date_not_report_date() -> None:
    gated = _primary_target("exact_form_with_lazy_index")
    filed_2000 = catalog_only_rows(
        "plan-1",
        _dated_scope("4", "2000-01-15", report_date="1999-12-31"),
        (gated,),
    )
    filed_1999 = catalog_only_rows(
        "plan-1",
        _dated_scope("4", "1999-12-30", report_date="2000-06-30"),
        (gated,),
    )

    assert filed_2000[0]["retrieval_mode"] == "bundle_sequence"
    assert filed_1999[0]["retrieval_mode"] == "bundle_scan"


def test_no_primary_without_filing_year_stays_unresolved() -> None:
    rows = catalog_only_rows(
        "plan-1",
        _dated_scope("4", ""),
        (_primary_target("exact_form_with_lazy_index"),),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["status_reason"] == "no_usable_primary_path"


def test_numbered_placeholder_constructs_direct_link_any_cohort() -> None:
    for filing_date in ("2024-03-01", "1998-03-01"):
        rows = catalog_only_rows(
            "plan-1",
            _dated_scope("4", filing_date, primary_document="0001.htm"),
            (_primary_target(None),),
        )

        assert rows[0]["status"] == "matched"
        assert rows[0]["retrieval_mode"] == "direct_url"
        assert rows[0]["target_url"] == f"{_ARCHIVE_ROOT}/{_ACCESSION}-0001.htm"
        assert rows[0]["status_reason"] is None


def test_zero_placeholder_pre2000_flows_to_bundle_scan() -> None:
    rows = catalog_only_rows(
        "plan-1",
        _dated_scope("4", "1999-06-01", primary_document="0000.txt"),
        (_primary_target(None),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["retrieval_mode"] == "bundle_scan"
    assert rows[0]["status_reason"] == "sgml_bundle_scan_pre2000"


def test_catalog_stub_link_is_not_selected() -> None:
    target = ProfileTarget("primary", "primary", False, "primary:primary")
    placeholder_url = f"{_ARCHIVE_ROOT}/{_ACCESSION}-0000.htm"
    rows = catalog_only_rows(
        "plan-1",
        _scope(
            placeholder_url,
            source_cik="898015",
            primary_document="0000.htm",
            accession=_ACCESSION,
        ),
        (target,),
    )

    assert rows[0]["status"] == "unresolved"
    assert rows[0]["target_url"] is None
