"""Tests for the operator's drill-down position and current-filing rows."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.client import operator, operator_drill, operator_drill_exhibits
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.forms.earnings.models import (
    EarningsExhibitResult,
    EarningsTable,
    EarningsTableRow,
    ExhibitCandidate,
    HeadlineFigure,
    HeadlineFigures,
    ReviewSignal,
)
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)
from edgar_sec.foundation.runtime.interactive import MenuAction
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow

PRIMARY_TEXT = (
    "Cover block line one.\nCover block line two.\n"
    "\n"
    "ITEM 1. BUSINESS\nBusiness body.\n"
    "\n"
    "ITEM 1A. RISK FACTORS\nRisk body.\n"
)
SECTION_TEXTS = {
    "ITEM 1": "ITEM 1. BUSINESS\nBusiness lead.\n\nBusiness details block.\n",
    "ITEM 1A": "ITEM 1A. RISK FACTORS\nRisk lead.\n\nRisk details block.\n",
}
NOTE_TEXTS = {
    1: "Note 1. Policies\nPolicy lead.\n\nPolicy details block.\n",
    2: "Note 2. Revenue\nRevenue lead.\n\nRevenue details block.\n",
}
EXHIBIT_TEXT = "Exhibit lead block.\n\nExhibit second block.\n"
BUNDLE_BYTES = b"<SEC-DOCUMENT>bundle-bytes"
_CIK = Cik.from_raw(320193)


def _section(item: str, title: str, start: int) -> ResolvedSection:
    return ResolvedSection(
        item_identifier=item,
        start_line=start,
        end_line=start + 2,
        title=title,
        raw_heading=item,
        kind=CandidateKind.STANDARD,
        confidence=1.0,
    )


def _note(number: int, title: str, start: int) -> ResolvedNote:
    return ResolvedNote(
        note_number=number,
        note_label=f"Note {number}",
        start_line=start,
        end_line=start + 2,
        title=title,
        raw_heading=f"Note {number}",
        confidence=1.0,
    )


class _FakeStatements:
    def by_category(self, category: str):
        if category != "statement":
            return ()
        from types import SimpleNamespace

        return (
            SimpleNamespace(title="Income Statement"),
            SimpleNamespace(title="Balance Sheet"),
        )


class _FakeXbrl:
    statements = _FakeStatements()
    facts = (1, 2, 3)


class _FakeFacade:
    def __init__(self, tmp_path: Path, *, earnings_absent: bool = False) -> None:
        self.artifacts_root = tmp_path
        self.calls: list = []
        self.earnings_absent = earnings_absent

    def sections(self, filing, text=None):
        return SectionSequence(
            family=filing.form,
            sections=(
                _section("ITEM 1", "Business", 3),
                _section("ITEM 1A", "Risk Factors", 6),
            ),
        )

    def section(self, filing, item, text=None):
        found = self.sections(filing).get(item)
        return SECTION_TEXTS[found.item_identifier] if found else ""

    def notes(self, filing, text=None):
        return NotesSequence(notes=(_note(1, "Policies", 9), _note(2, "Revenue", 12)))

    def note(self, filing, number, text=None):
        return NOTE_TEXTS.get(int(number), "")

    def toc(self, filing, text=None):
        return TocSpan(
            start_line=0,
            end_line=1,
            start_offset=0,
            end_offset=40,
            method="heuristic",
            confidence=0.9,
        )

    def xbrl(self, filing):
        return _FakeXbrl()

    def earnings_exhibit(self, filing):
        accession = filing.accession.value
        if self.earnings_absent:
            return EarningsExhibitResult(
                accession=accession,
                form=filing.form,
                exhibit=None,
                tables=(),
                headline=None,
                review_signals=(),
                text="",
                absence_reason="no EX-99 exhibit attached",
            )
        candidate = ExhibitCandidate(
            filename="ex99-1.htm",
            document_type="EX-99.1",
            exhibit_number=99,
            family="8-K",
            kind="earnings_release",
        )
        table = EarningsTable(
            table_index=0,
            caption="Results",
            periods=("2024", "2023"),
            rows=(
                EarningsTableRow("Revenue", ("100", "90")),
                EarningsTableRow("Net income", ("10", "8")),
            ),
            roles=(),
        )
        headline = HeadlineFigures(
            revenue=HeadlineFigure("Revenue", "100"),
            net_income=HeadlineFigure("Net income", "10"),
            eps=HeadlineFigure("Diluted EPS", "1.00"),
            source_table_index=0,
            locus="table 0",
        )
        signal = ReviewSignal(
            kind="unstructured_table",
            specimen_class="chart",
            filename="ex99-1.htm",
            detail="one chart not structured",
        )
        return EarningsExhibitResult(
            accession=accession,
            form=filing.form,
            exhibit=candidate,
            tables=(table,),
            headline=headline,
            review_signals=(signal,),
            text="release text",
        )


def _filing(
    tmp_path: Path,
    form: str = "10-K",
    number: int = 106,
    *,
    bundle: bool = True,
) -> FilingAggregate:
    primary = tmp_path / f"primary-{number}.txt"
    primary.write_text(PRIMARY_TEXT, encoding="utf-8")
    attachments = [
        FilingAttachment(
            attachment_id="ex99",
            document_type="EX-99.1",
            filename="ex99-1.htm",
            url="",
            fetcher=lambda a: EXHIBIT_TEXT.encode(),
        ),
        FilingAttachment(
            attachment_id="ex31",
            document_type="EX-31.1",
            filename="ex31-1.htm",
            url="",
            fetcher=lambda a: b"Certification text.",
        ),
    ]
    if form in ("10-K", "8-K"):
        attachments.append(
            FilingAttachment(
                attachment_id="cal",
                document_type="XML",
                filename="filing_cal.xml",
                url="",
            )
        )
    return FilingAggregate(
        accession=AccessionNumber.from_any(f"0000320193-23-{number:06d}"),
        primary_cik=_CIK,
        ciks=(_CIK,),
        form=form,
        filing_date="2023-11-03",
        primary_document_path="primary.txt",
        primary_storage_path=primary,
        attachments=tuple(attachments),
        bundle_fetcher=(lambda agg: BUNDLE_BYTES) if bundle else None,
    )


def _session(tmp_path: Path, filing: FilingAggregate, **facade_kwargs):
    session = operator.ClientSession(facade=_FakeFacade(tmp_path, **facade_kwargs))
    session.select_filing(filing.accession.value, aggregate=filing)
    return session


def _run(op_id: str, session, options: dict | None = None):
    return operator.execute_by_id(op_id, session, options or {})


def _menu_labels(session) -> list[str]:
    menu = operator.build_operator_menu(session)
    return [item.label for item in menu if isinstance(item, MenuAction)]


def _result(tmp_path: Path, filings: list[FilingAggregate]) -> FilingsResult:
    return FilingsResult(
        run_id="run-x",
        plan_id="plan-x",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=tuple(filings),
    )


def test_drill_rows_registered_with_availability() -> None:
    for op_id in (
        "select_filing",
        "back",
        "primary_document",
        "sections_list",
        "read_section",
        "notes_list",
        "read_note",
        "filing_toc",
        "exhibits_list",
        "read_exhibit",
        "xbrl_summary",
        "earnings_exhibit",
        "save_payload",
        "save_bundle",
    ):
        assert op_id in operator.REGISTRY
    assert operator.REGISTRY["sections_list"].available is not None
    assert operator.REGISTRY["earnings_exhibit"].available is not None
    assert operator.REGISTRY["primary_document"].available is None
    assert operator.REGISTRY["session_summary"].available is None
    assert "select_filing" in operator_drill.GATHERERS
    assert "read_section" in operator_drill.GATHERERS
    assert "read_exhibit" in operator_drill_exhibits.GATHERERS


def test_select_filing_moves_position_and_header(tmp_path: Path) -> None:
    filing = _filing(tmp_path)
    other = _filing(tmp_path, number=107)
    session = operator.ClientSession(facade=_FakeFacade(tmp_path))
    session.add_set(
        "main",
        [filing.accession.value, other.accession.value],
        result=_result(tmp_path, [filing, other]),
    )
    result = _run("select_filing", session, {"accession": filing.accession.value})
    assert result.error_code is None
    assert session.current_filing is not None
    assert session.current_filing.aggregate is filing
    header = operator.render_session_header(session)
    assert f"current filing: {filing.accession.value}" in header
    missing = _run("select_filing", session, {"accession": "0000000000-00-000000"})
    assert missing.error_code == "not_found"


def test_select_from_accessions_only_set_refuses_coded(tmp_path: Path) -> None:
    filing = _filing(tmp_path)
    session = operator.ClientSession(facade=_FakeFacade(tmp_path))
    session.add_set("main", [filing.accession.value])
    result = _run("select_filing", session, {"accession": filing.accession.value})
    assert result.error_code == "refused"
    assert "aggregates" in result.data["message"]
    assert session.current_filing is None


def test_back_clears_position_and_header(tmp_path: Path) -> None:
    filing = _filing(tmp_path)
    session = _session(tmp_path, filing)
    result = _run("back", session)
    assert result.error_code is None
    assert result.data["cleared"] == filing.accession.value
    assert session.current_filing is None
    assert "current filing: none" in operator.render_session_header(session)


def test_menu_gates_rows_on_filing_capabilities(tmp_path: Path) -> None:
    capable = _menu_labels(_session(tmp_path, _filing(tmp_path)))
    for label in ("List sections", "List notes", "Table of contents", "XBRL summary"):
        assert label in capable
    assert "Earnings exhibit" not in capable
    current = _menu_labels(
        _session(tmp_path, _filing(tmp_path, form="8-K", number=108))
    )
    assert "Earnings exhibit" in current
    assert "List notes" not in current
    assert "Table of contents" not in current
    incapable = _menu_labels(
        _session(tmp_path, _filing(tmp_path, form="4", number=109))
    )
    for label in (
        "List sections",
        "List notes",
        "Table of contents",
        "XBRL summary",
        "Earnings exhibit",
    ):
        assert label not in incapable
    for label in (
        "Primary document text",
        "List exhibits",
        "Save payload",
        "Back (clear filing)",
    ):
        assert label in incapable


def test_menu_availability_no_filing_then_capable_then_incapable(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from edgar_sec.domain.forms.families.current.processing import (
        PROFILE as _CURRENT,
    )

    gated = (
        "List sections",
        "Read one section",
        "List notes",
        "Read one note",
        "Table of contents",
        "XBRL summary",
        "Earnings exhibit",
    )
    no_filing = operator.ClientSession(facade=_FakeFacade(tmp_path))
    for label in gated:
        assert label not in _menu_labels(no_filing)
    capable_agg = SimpleNamespace(
        has_sections=True,
        has_notes=True,
        has_toc=True,
        has_xbrl=True,
        processing_profile=_CURRENT,
    )
    capable = operator.ClientSession(facade=_FakeFacade(tmp_path))
    capable.select_filing("0000320193-25-000001", aggregate=capable_agg)
    for label in gated:
        assert label in _menu_labels(capable)
    incapable_agg = SimpleNamespace(
        has_sections=False,
        has_notes=False,
        has_toc=False,
        has_xbrl=False,
        processing_profile=SimpleNamespace(family="other"),
    )
    incapable = operator.ClientSession(facade=_FakeFacade(tmp_path))
    incapable.select_filing("0000320193-25-000002", aggregate=incapable_agg)
    for label in gated:
        assert label not in _menu_labels(incapable)


def test_primary_document_detail_dial(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    minimal = _run("primary_document", session, {"detail": "minimal"})
    assert minimal.error_code is None
    assert minimal.data["text"] == PRIMARY_TEXT.split("\n\n")[0]
    assert minimal.data["full_size"] == len(PRIMARY_TEXT)
    assert minimal.data["shown_size"] < minimal.data["full_size"]
    assert minimal.data["detail"] == "minimal"
    assert "context" not in minimal.data
    standard = _run("primary_document", session, {"detail": "standard"})
    assert standard.data["text"] == PRIMARY_TEXT
    assert standard.data["text"].endswith("Risk body.\n")
    full = _run("primary_document", session, {"detail": "full"})
    assert full.data["text"] == PRIMARY_TEXT
    assert full.data["context"]["position"] == 1
    assert full.data["context"]["total"] == 1
    bad = _run("primary_document", session, {"detail": "first-100-chars"})
    assert bad.error_code == "invalid_options"


def test_sections_list_and_read_section(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    listing = _run("sections_list", session, {"limit": 1})
    assert listing.error_code is None
    assert (listing.total, listing.shown) == (2, 1)
    assert listing.data["sections"][0]["item"] == "ITEM 1"
    read = _run("read_section", session, {"item": "1A", "detail": "full"})
    assert read.error_code is None
    assert read.data["text"] == SECTION_TEXTS["ITEM 1A"]
    assert read.data["context"]["position"] == 2
    assert read.data["context"]["total"] == 2
    assert read.data["context"]["previous_title"] == "Business"
    assert read.data["context"]["next_title"] is None
    minimal = _run("read_section", session, {"item": "ITEM 1", "detail": "minimal"})
    assert minimal.data["text"] == "ITEM 1. BUSINESS\nBusiness lead."
    assert minimal.data["full_size"] == len(SECTION_TEXTS["ITEM 1"])
    missing = _run("read_section", session, {"item": "ITEM 99"})
    assert missing.error_code == "not_found"


def test_sections_and_notes_absent_on_form4(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path, form="4", number=110))
    for op_id, options in (
        ("sections_list", {}),
        ("read_section", {"item": "ITEM 1"}),
        ("notes_list", {}),
        ("read_note", {"number": 1}),
        ("filing_toc", {}),
        ("xbrl_summary", {}),
    ):
        result = _run(op_id, session, options)
        assert result.error_code == "absent", op_id
        assert result.data["present"] is False


def test_notes_list_and_read_note(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    listing = _run("notes_list", session)
    assert listing.error_code is None
    assert (listing.total, listing.shown) == (2, 2)
    assert listing.data["notes"][1]["number"] == 2
    read = _run("read_note", session, {"number": 2, "detail": "standard"})
    assert read.data["text"] == NOTE_TEXTS[2]
    assert read.data["full_size"] == len(NOTE_TEXTS[2])
    missing = _run("read_note", session, {"number": 9})
    assert missing.error_code == "not_found"


def test_toc_renders_span(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    result = _run("filing_toc", session)
    assert result.error_code is None
    assert result.data["present"] is True
    assert result.data["start_line"] == 0
    assert result.data["method"] == "heuristic"


def test_exhibits_grid_and_read_exhibit(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    listing = _run("exhibits_list", session, {"limit": 1})
    assert listing.error_code is None
    assert (listing.total, listing.shown) == (2, 1)
    assert listing.data["exhibits"][0]["document_type"] == "EX-99.1"
    read = _run("read_exhibit", session, {"exhibit": "EX-99.1", "detail": "minimal"})
    assert read.error_code is None
    assert read.data["text"] == "Exhibit lead block."
    assert read.data["full_size"] == len(EXHIBIT_TEXT)
    assert read.data["filename"] == "ex99-1.htm"
    full = _run("read_exhibit", session, {"exhibit": "ex99-1.htm", "detail": "full"})
    assert full.data["text"] == EXHIBIT_TEXT
    assert full.data["context"]["position"] == 1
    assert full.data["context"]["next_title"] == "EX-31.1 ex31-1.htm"
    missing = _run("read_exhibit", session, {"exhibit": "EX-42"})
    assert missing.error_code == "not_found"


def test_xbrl_summary(tmp_path: Path) -> None:
    session = _session(tmp_path, _filing(tmp_path))
    result = _run("xbrl_summary", session)
    assert result.error_code is None
    assert result.data["available"] is True
    assert result.data["fact_count"] == 3
    assert result.data["statements"] == ["Income Statement", "Balance Sheet"]
    assert result.data["statement_count"] == 2


def test_earnings_exhibit_renders_identity_tables_headline_signals(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, _filing(tmp_path, form="8-K", number=111))
    result = _run("earnings_exhibit", session)
    assert result.error_code is None
    assert result.kind == "object"
    assert result.data["exhibit"]["filename"] == "ex99-1.htm"
    assert result.data["headline"]["revenue"] == {"label": "Revenue", "value": "100"}
    assert result.data["headline"]["eps"]["value"] == "1.00"
    assert result.data["tables"][0]["rows"][0] == {
        "label": "Revenue",
        "values": ["100", "90"],
    }
    assert result.data["review_signals"][0]["kind"] == "unstructured_table"
    kinds = {type(c) for c in result.components}
    assert Grid in kinds and KeyValueRow in kinds and ProseRow in kinds


def test_earnings_absent_cases(tmp_path: Path) -> None:
    annual = _session(tmp_path, _filing(tmp_path))
    result = _run("earnings_exhibit", annual)
    assert result.error_code == "absent"
    assert result.data["present"] is False
    empty = _session(
        tmp_path, _filing(tmp_path, form="8-K", number=112), earnings_absent=True
    )
    result = _run("earnings_exhibit", empty)
    assert result.error_code == "absent"
    assert "no EX-99 exhibit" in result.data["message"]


def test_save_payload_explicit_and_default(tmp_path: Path) -> None:
    filing = _filing(tmp_path)
    session = _session(tmp_path, filing)
    target = tmp_path / "out" / "saved.txt"
    result = _run("save_payload", session, {"path": str(target)})
    assert result.error_code is None
    assert target.read_bytes() == PRIMARY_TEXT.encode()
    assert result.data["path"] == str(target)
    assert result.data["size"] == len(PRIMARY_TEXT.encode())
    defaulted = _run("save_payload", session)
    expected = tmp_path / "operator-saves" / f"{filing.accession.value}-primary.txt"
    assert defaulted.data["path"] == str(expected)
    assert expected.is_file()
    assert defaulted.data["size"] == expected.stat().st_size


def test_save_bundle_and_bundle_absence(tmp_path: Path) -> None:
    filing = _filing(tmp_path)
    session = _session(tmp_path, filing)
    result = _run("save_bundle", session)
    assert result.error_code is None
    path = Path(result.data["path"])
    assert path.parent.name == "operator-saves"
    assert path.read_bytes() == BUNDLE_BYTES
    assert result.data["size"] == len(BUNDLE_BYTES)
    no_bundle = _session(tmp_path, _filing(tmp_path, number=113, bundle=False))
    result = _run("save_bundle", no_bundle)
    assert result.error_code == "absent"
    assert result.data["present"] is False


def test_gatherers_pick_from_live_lists(tmp_path: Path, monkeypatch) -> None:
    filing = _filing(tmp_path)
    session = _session(tmp_path, filing)
    seen: dict[str, list] = {}

    def fake_pick(items, **kwargs):
        seen[kwargs.get("prompt_label", "")] = list(items)
        return items[0] if items else None

    monkeypatch.setattr(operator_drill, "prompt_paginated_choice", fake_pick)
    monkeypatch.setattr(operator_drill_exhibits, "prompt_paginated_choice", fake_pick)
    monkeypatch.setattr(operator_drill, "prompt_choice", lambda *a, **k: "standard")
    section_options = operator_drill.GATHERERS["read_section"](session)
    assert section_options.item == "ITEM 1"
    assert [i.key for i in seen["Select section"]] == ["ITEM 1", "ITEM 1A"]
    note_options = operator_drill.GATHERERS["read_note"](session)
    assert note_options.number == 1
    exhibit_options = operator_drill_exhibits.GATHERERS["read_exhibit"](session)
    assert exhibit_options.exhibit == "ex99-1.htm"
    session.add_set(
        "main", [filing.accession.value], result=_result(tmp_path, [filing])
    )
    session.current_set_name = "main"
    select_options = operator_drill.GATHERERS["select_filing"](session)
    assert select_options.accession == filing.accession.value
    assert seen["Select filing"][0].key == filing.accession.value
