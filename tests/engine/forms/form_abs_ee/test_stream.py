from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.forms.families.form_abs_ee.models import ExhibitKind
from edgar_sec.engine.forms.form_abs_ee.stream import (
    classify_asset_root,
    detect_companions,
    summarize_asset_data,
)

_EX102 = b"""<?xml version="1.0" encoding="UTF-8"?>
<assetData xmlns="http://www.sec.gov/edgar/document/absee/autolease/assetdata">
<!-- DISCLAIMER: sample -->
<assets><assetNumber>1</assetNumber></assets>
<assets><assetNumber>2</assetNumber><!-- loan note --></assets>
<assets><assetNumber>3</assetNumber></assets>
</assetData>
"""

_EX103 = b"""<?xml version="1.0" encoding="UTF-8"?>
<assetdata>
<assets><assetNumber>2003</assetNumber><!-- narrative one --><![CDATA[ free text ]]></assets>
<assets><assetNumber>2004</assetNumber><!-- narrative two --></assets>
</assetdata>
"""


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_classify_roots() -> None:
    assert classify_asset_root(
        "http://www.sec.gov/edgar/document/absee/cmbs/assetdata", "assetData"
    ) == (ExhibitKind.EX_102, "cmbs")
    assert classify_asset_root("", "assetdata") == (ExhibitKind.EX_103, None)
    assert classify_asset_root("", "edgarSubmission") is None
    assert classify_asset_root("http://example.com/x", "assetData") is None


def test_summarize_ex102_streams_records_and_comments(tmp_path: Path) -> None:
    summary = summarize_asset_data(_write(tmp_path, "ex102.xml", _EX102))
    assert summary is not None
    assert summary.kind is ExhibitKind.EX_102
    assert summary.asset_class == "autolease"
    assert summary.record_count == 3
    assert summary.comment_count == 2
    assert summary.cdata_sections == 0


def test_summarize_ex103_counts_comments_and_cdata(tmp_path: Path) -> None:
    summary = summarize_asset_data(_write(tmp_path, "ex103.xml", _EX103))
    assert summary is not None
    assert summary.kind is ExhibitKind.EX_103
    assert summary.asset_class is None
    assert summary.record_count == 2
    assert summary.comment_count == 2
    assert summary.comment_chars > 0
    assert summary.cdata_sections == 1


_EX103_COMMENTS = b"""<?xml version="1.0" encoding="utf-8"?>
<comments>
<commentData><itemNumber>Item 2(c)(15)</itemNumber><comment>note one</comment></commentData>
<commentData><itemNumber>Item 3</itemNumber><comment>note two</comment></commentData>
</comments>
"""

_EX103_NARRATIVE_ONLY = b"""<?xml version="1.0" encoding="UTF-8"?>
<assetdata>
<!-- Exhibit 103 -->
<!-- This document provides narrative for the asset-level data. -->
</assetdata>
"""


def test_classify_comments_root_as_ex103() -> None:
    assert classify_asset_root("", "comments") == (ExhibitKind.EX_103, None)


def test_summarize_cmbs_comment_data_shape(tmp_path: Path) -> None:
    summary = summarize_asset_data(_write(tmp_path, "cmbs103.xml", _EX103_COMMENTS))
    assert summary is not None
    assert summary.kind is ExhibitKind.EX_103
    assert summary.root_tag == "comments"
    assert summary.record_count == 2


def test_summarize_narrative_only_ex103(tmp_path: Path) -> None:
    summary = summarize_asset_data(_write(tmp_path, "narr.xml", _EX103_NARRATIVE_ONLY))
    assert summary is not None
    assert summary.record_count == 0
    assert summary.comment_count == 2


def test_summarize_rejects_non_asset_documents(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "other.xml", b"<edgarSubmission><formData/></edgarSubmission>"
    )
    assert summarize_asset_data(path) is None


def test_detect_companions_from_document_types() -> None:
    signals = detect_companions(["10-D", "EX-102", "ex-103 ", "EX-99"])
    assert [(s.exhibit_type, s.present) for s in signals] == [
        ("EX-102", True),
        ("EX-103", True),
    ]
    signals = detect_companions(["EX-99"])
    assert [s.present for s in signals] == [False, False]
