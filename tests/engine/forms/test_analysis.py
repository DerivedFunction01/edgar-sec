"""Tests for shared form case analysis and scorecard aggregation."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    rebuild_table_geometries,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.normalize import normalize_document

_SAMPLE_10K_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 10-K
ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934
ACME CORP
(Exact name of registrant as specified in its charter)
Large accelerated filer [X]   Accelerated filer [ ]   Non-accelerated filer [ ]
Item 1. Business
Acme designs and manufactures advanced widgets.
Item 1A. Risk Factors
Our operations involve operational risks.
Item 7. Management's Discussion and Analysis of Financial Condition
Results of operations improved significantly.
Item 8. Financial Statements and Supplementary Data
Note 1. Summary of Accounting Policies
The financial statements have been prepared in accordance with GAAP.
Note 2. Revenues
Revenues are recognized when control transfers.
"""


def test_reinfer_unmasked_checkmarks_merges_without_downgrade() -> None:
    text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\n"
        "SCHEDULE 14A\n"
        "Check the appropriate box:\n"
        "<TABLE>\n[X] Definitive Proxy Statement\n</TABLE>\n"
        "<TABLE>\n[ ] Preliminary Proxy Statement\n</TABLE>\n"
        "Notice of Annual Meeting\nThe board of directors recommends a vote.\n"
    )
    rep: dict = {
        "checkmarks": {
            "candidate_states": {"classification_preliminary": "checked"},
            "checked_keys": ("classification_preliminary",),
        }
    }
    reinfer_unmasked_checkmarks(text, rep, family="14A")
    states = rep["checkmarks"]["candidate_states"]
    assert states["classification_definitive"] == "checked"
    assert states["classification_preliminary"] == "checked"
    assert "classification_definitive" in rep["checkmarks"]["checked_keys"]


def test_locate_text_artifact_finds_preferred(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    render_txt = ops / "render_to_txt.txt"
    render_txt.write_text("sample", encoding="utf-8")
    assert locate_text_artifact(tmp_path) == render_txt


def test_locate_text_artifact_missing(tmp_path: Path) -> None:
    assert locate_text_artifact(tmp_path) is None


def test_analyze_form_case_10k(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    (ops / "render_to_txt.txt").write_text(_SAMPLE_10K_TEXT, encoding="utf-8")

    record = {"accession": "0000001000-24-000001", "form": "10-K"}
    rep = analyze_form_case(tmp_path, record)
    assert rep is not None
    assert rep["form"] == "10-K"
    assert rep["family"] == "10-K"
    assert rep["checkmarks"]["filer_status"] == "large_accelerated_filer"
    assert "ITEM 1" in rep["taxonomy"]["detected_items"]
    assert "ITEM 1A" in rep["taxonomy"]["detected_items"]
    assert "NOTE 1" in rep["notes"]["detected_notes"]


def test_summarize_form_cases(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    (ops / "render_to_txt.txt").write_text(_SAMPLE_10K_TEXT, encoding="utf-8")

    record = {"accession": "0000001000-24-000001", "form": "10-K"}
    rep = analyze_form_case(tmp_path, record)
    assert rep is not None

    summary = summarize_form_cases([rep], family="10-K")
    assert summary["case_count"] == 1
    assert (
        summary["checkmark_scorecard"]["filer_status_counts"]["large_accelerated_filer"]
        == 1
    )
    assert "ITEM 1" in summary["taxonomy_scorecard"]["item_coverage"]


def test_anomaly_record_shape() -> None:
    assert anomaly_record("missing_field", "no value matched") == {
        "kind": "missing_field",
        "details": "no value matched",
        "detail": "no value matched",
    }


_SURVIVING_TABLE_HTML = """\
<html><body>
<pre>
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
SCHEDULE 14A
Proxy Statement Pursuant to Section 14(a) of the Securities Exchange Act of 1934
Filed by the Registrant [X] Filed by a Party other than the Registrant [ ]
Check the appropriate box:
</pre>
<table>
<tr><td>[ ]</td><td>Preliminary Proxy Statement</td></tr>
<tr><td>[X]</td><td>Definitive Proxy Statement</td></tr>
<tr><td>[ ]</td><td>Definitive Additional Materials</td></tr>
</table>
<pre>
ACME CORPORATION
(Name of Registrant as Specified In Its Charter)
NOTICE OF ANNUAL MEETING OF STOCKHOLDERS
The annual meeting of stockholders of Acme Corporation will be held on June 12, 2026.
</pre>
</body></html>"""

_MIXED_TABLE_HTML = """\
<html><body>
<pre>
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
SCHEDULE 14A
Check the appropriate box:
</pre>
<table>
<tr><td>[X]</td><td>Definitive Proxy Statement</td></tr>
<tr><td>[ ]</td><td>Preliminary Proxy Statement</td></tr>
<tr><td>___</td><td>Definitive Additional Materials</td></tr>
</table>
<pre>
Notice of Annual Meeting
The board of directors recommends a vote.
</pre>
</body></html>"""


def _write_review_case(root: Path, text: str, raw: bytes | None) -> Path:
    """Build a minimal review artifact holding text and optional raw bytes."""
    case_dir = root / "case"
    ops_dir = case_dir / "operations"
    ops_dir.mkdir(parents=True)
    (ops_dir / "render_to_txt.txt").write_text(text, encoding="utf-8")
    sidecar = {"accession": "0000000000-26-000001", "form": "DEF 14A"}
    (case_dir / "processing-review.json").write_text(
        json.dumps(sidecar), encoding="utf-8"
    )
    if raw is not None:
        (ops_dir / "raw.htm").write_bytes(raw)
    return case_dir


def test_rebuild_table_geometries_reproduces_production(
    tmp_path: Path,
) -> None:
    """The replay returns production's exact geometries for a live case."""
    raw = _SURVIVING_TABLE_HTML.encode()
    production = normalize_document(raw, form="DEF 14A", document_path="raw.htm")
    assert production.table_geometries
    case_dir = _write_review_case(tmp_path, production.text, raw)
    rebuilt = rebuild_table_geometries(case_dir, production.text, form="DEF 14A")
    assert rebuilt == production.table_geometries


def test_rebuild_table_geometries_falls_back_when_unavailable(
    tmp_path: Path,
) -> None:
    """Stale text, a missing raw artifact, or span-free text yields None."""
    raw = _SURVIVING_TABLE_HTML.encode()
    production = normalize_document(raw, form="DEF 14A", document_path="raw.htm")
    case_dir = _write_review_case(tmp_path, production.text, raw)
    stale = production.text + "\nan extra line"
    assert rebuild_table_geometries(case_dir, stale, form="DEF 14A") is None
    assert rebuild_table_geometries(case_dir, "no tables here", form="DEF 14A") is None
    bare_dir = _write_review_case(tmp_path / "bare", production.text, None)
    assert rebuild_table_geometries(bare_dir, production.text, form="DEF 14A") is None


def test_analyze_form_case_uses_rebuilt_geometries(tmp_path: Path) -> None:
    """With raw bytes persisted, analyze matches production's table states."""
    raw = _MIXED_TABLE_HTML.encode()
    production = normalize_document(raw, form="DEF 14A", document_path="raw.htm")
    sidecar = {"accession": "0000000000-26-000001", "form": "DEF 14A"}
    case_dir = _write_review_case(tmp_path / "geo", production.text, raw)
    rep = analyze_form_case(case_dir, sidecar)
    assert rep is not None
    assert rep["checkmarks"]["candidate_states"] == {
        "classification_definitive": "checked",
        "classification_preliminary": "unchecked",
        "classification_definitive_additional": None,
    }
    bare_dir = _write_review_case(tmp_path / "bare", production.text, None)
    bare_rep = analyze_form_case(bare_dir, sidecar)
    assert bare_rep is not None
    assert bare_rep["checkmarks"]["candidate_states"] == {}


def test_reinfer_with_case_dir_geometries_and_fallback(tmp_path: Path) -> None:
    """Reinfer resolves table states with geometries and on the fallback."""
    raw = _MIXED_TABLE_HTML.encode()
    production = normalize_document(raw, form="DEF 14A", document_path="raw.htm")
    case_dir = _write_review_case(tmp_path / "geo", production.text, raw)
    expected = {
        "classification_definitive": "checked",
        "classification_preliminary": "unchecked",
    }
    rep: dict = {"checkmarks": {"candidate_states": {}, "checked_keys": ()}}
    reinfer_unmasked_checkmarks(production.text, rep, family="14A", case_dir=case_dir)
    assert rep["checkmarks"]["candidate_states"] == expected
    bare_dir = _write_review_case(tmp_path / "bare", production.text, None)
    fallback_rep: dict = {"checkmarks": {"candidate_states": {}, "checked_keys": ()}}
    reinfer_unmasked_checkmarks(
        production.text, fallback_rep, family="14A", case_dir=bare_dir
    )
    assert fallback_rep["checkmarks"]["candidate_states"] == expected
