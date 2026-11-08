"""Tests for the operator's feed, EFTS, and local-search rows."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from edgar_sec.apps.client import operator, operator_run_records, operator_selection
from edgar_sec.apps.client import operator_tools
from edgar_sec.apps.client.efts import (
    EftsCapture,
    EftsCoverage,
    EftsHit,
    EftsHitIdentity,
    EftsSearchResult,
)
from edgar_sec.apps.client.feeds import FeedEventsResult, FeedLedgerEvent
from edgar_sec.engine.text_search.models import (
    Coverage,
    SearchHit,
    SearchResult,
    TargetVerdict,
)
from edgar_sec.foundation.runtime.render import Grid, ProseRow


def _event(accession: str, form: str = "8-K") -> FeedLedgerEvent:
    return FeedLedgerEvent(
        accession=accession,
        cik="0000000123",
        form=form,
        company_name="Acme Corp",
        filing_date=date(2026, 1, 2),
        acceptance_datetime=datetime(2026, 1, 2, 12, 0),
        link="https://example.test/filing",
        sources=("atom",),
        fetched_at="2026-01-02T12:00:00Z",
    )


def _hit(accession: str, score: float = 1.5) -> EftsHit:
    return EftsHit(
        document_id=f"{accession}:doc.htm",
        accession=accession,
        filename="doc.htm",
        score=score,
        ciks=("0000000123",),
        display_names=("Acme Corp",),
        form="8-K",
        root_forms=("8-K",),
        file_date="2026-01-02",
        period_ending=None,
        file_type="EX-99.1",
        file_description=None,
        items=("2.02",),
        sics=(),
        biz_states=(),
        biz_locations=(),
        inc_states=(),
        file_num=(),
        film_num=(),
        sequence=1,
        xsl=None,
    )


def _coverage(**overrides) -> Coverage:
    values = {
        "index_present": True,
        "source_snapshot_id": "snap-1",
        "built_at": "2026-01-01T00:00:00Z",
        "accessions_searched": 2,
        "documents_searched": 5,
        "chunks_searched": 9,
        "targets": (),
    }
    values.update(overrides)
    return Coverage(**values)


class _FakeFacade:
    """Facade stand-in serving canned feed, EFTS, and search results."""

    def __init__(self, tmp_path: Path) -> None:
        self.artifacts_root = tmp_path
        self.calls: list[tuple[str, dict]] = []
        self.feed_result = FeedEventsResult(
            events=(_event("A1"), _event("A2", "10-K"), _event("A3")),
            snapshot_id="tip-1",
            ledger_present=True,
        )
        self.efts_result = EftsSearchResult(
            hits=(_hit("A1"), _hit("A2"), _hit("A3")),
            coverage=EftsCoverage(
                total_value=250,
                total_relation="eq",
                hits_returned=3,
                truncated=True,
            ),
        )
        self.capture_result = EftsCapture(
            directory=tmp_path / "queries" / "efts" / "abc",
            query_hash="abc123",
            executed_at="2026-01-02T00:00:00Z",
            coverage=EftsCoverage(
                total_value=2,
                total_relation="eq",
                hits_returned=2,
                truncated=False,
            ),
            identities=(
                EftsHitIdentity(
                    "A1:doc.htm", "A1", "doc.htm", "123", "8-K", "2026-01-02"
                ),
                EftsHitIdentity(
                    "A2:doc.htm", "A2", "doc.htm", "123", "8-K", "2026-01-02"
                ),
            ),
        )
        self.search_result = SearchResult(
            query="revenue",
            mode="bm25",
            hits=(
                SearchHit(
                    "A1", "doc.htm", None, None, "ITEM 7", None, 1, 4, "one", 2.0
                ),
                SearchHit(
                    "A2", "doc.htm", None, None, "ITEM 8", None, 1, 4, "two", 1.0
                ),
            ),
            coverage=_coverage(),
        )

    def feed_events(self, **kwargs):
        self.calls.append(("feed_events", kwargs))
        return self.feed_result

    def full_text_search(self, **kwargs):
        self.calls.append(("full_text_search", kwargs))
        if not kwargs["text"] and not kwargs["forms"] and not kwargs["ciks"]:
            raise ValueError("a query needs text, forms, or ciks")
        return self.efts_result

    def capture_full_text_search(self, query, *, exhaustive=False):
        self.calls.append(("capture", {"query": query, "exhaustive": exhaustive}))
        return self.capture_result

    def search_documents(self, query, **kwargs):
        self.calls.append(("search_documents", {"query": query, **kwargs}))
        return self.search_result

    def cache_stats(self):
        return {"responses": {"entries": 3}}


def _session(tmp_path: Path) -> tuple[operator.ClientSession, _FakeFacade]:
    facade = _FakeFacade(tmp_path)
    return operator.ClientSession(facade=facade), facade


def test_new_tool_rows_have_the_ruled_effects() -> None:
    effects = {
        "feed_events": "reads_state",
        "feed_seed": "mutates_selection",
        "efts_search": "reads_state",
        "efts_capture": "external",
        "local_search": "reads_state",
        "local_search_seed": "mutates_selection",
    }
    for op_id, effect in effects.items():
        assert operator.REGISTRY[op_id].effect == effect


def test_feed_events_absent_ledger_is_prose_absence(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.feed_result = FeedEventsResult(
        events=(), snapshot_id=None, ledger_present=False
    )
    result = operator.execute_by_id("feed_events", session, {})
    assert result.error_code == "absent"
    assert result.data["present"] is False
    assert result.total == result.shown == 0
    assert result.components
    assert all(isinstance(row, ProseRow) for row in result.components)
    assert not any(isinstance(row, Grid) for row in result.components)


def test_feed_events_present_grid_declares_total_vs_shown(tmp_path) -> None:
    session, facade = _session(tmp_path)
    result = operator.execute_by_id("feed_events", session, {"forms": ["8-K"]})
    assert result.error_code is None
    assert (result.total, result.shown) == (3, 3)
    assert result.data["snapshot_id"] == "tip-1"
    assert result.data["events"][1]["form"] == "10-K"
    assert facade.calls[0][1]["forms"] == ("8-K",)


def test_feed_seed_stores_event_accessions(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("feed_seed", session, {"into": "feed"})
    assert result.error_code is None
    assert result.data["count"] == 3
    assert session.sets["feed"].accessions == frozenset({"A1", "A2", "A3"})
    assert session.current_set_name == "feed"


def test_feed_seed_absent_ledger_seeds_nothing(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.feed_result = FeedEventsResult(
        events=(), snapshot_id=None, ledger_present=False
    )
    result = operator.execute_by_id("feed_seed", session, {"into": "feed"})
    assert result.error_code == "absent"
    assert "feed" not in session.sets


def test_efts_search_declares_result_total_vs_shown(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"text": "revenue", "limit": 2}
    result = operator.execute_by_id("efts_search", session, options)
    assert result.error_code is None
    assert result.total == 250
    assert result.shown == 2
    assert result.data["coverage"]["total_value"] == 250
    assert result.data["coverage"]["hits_returned"] == 3
    assert result.data["hits"][0]["accession"] == "A1"


def test_efts_search_blank_query_is_invalid_options(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("efts_search", session, {})
    assert result.error_code == "invalid_options"


def test_efts_capture_refuses_unconfirmed_and_writes_nothing(tmp_path) -> None:
    session, facade = _session(tmp_path)
    result = operator.execute_by_id("efts_capture", session, {"text": "revenue"})
    assert result.error_code == "refused"
    assert not any(name == "capture" for name, _ in facade.calls)
    assert operator_run_records.list_records(session) == []


def test_efts_capture_confirmed_records_the_external_run(tmp_path) -> None:
    session, facade = _session(tmp_path)
    options = {"text": "revenue", "confirm": True}
    result = operator.execute_by_id("efts_capture", session, options)
    assert result.error_code is None
    assert result.data["capture"]["directory"] == str(facade.capture_result.directory)
    assert result.data["capture"]["query_hash"] == "abc123"
    records = operator_run_records.list_records(session)
    assert len(records) == 1
    assert records[0]["operation"] == "efts_capture"
    assert records[0]["result"]["directory"] == str(facade.capture_result.directory)
    assert records[0]["member_accounting"]["success_count"] == 2
    assert records[0]["options"]["confirm"] is True
    assert session.last_run_record == records[0]["record_id"]


def test_local_search_coverage_block_is_verbatim(tmp_path) -> None:
    session, facade = _session(tmp_path)
    coverage = _coverage(targets=(TargetVerdict("A9", False),))
    facade.search_result = SearchResult(
        query="revenue",
        mode="bm25",
        hits=(),
        coverage=coverage,
        not_in_corpus=("A9",),
    )
    result = operator.execute_by_id("local_search", session, {"query": "revenue"})
    expected = json.loads(json.dumps(asdict(coverage)))
    carried = json.loads(json.dumps(result.data["coverage"]))
    assert carried == expected
    prose = [row.text for row in result.components if isinstance(row, ProseRow)]
    assert "index_present: True" in prose
    assert "accessions_searched: 2" in prose


def test_local_search_not_in_corpus_is_not_a_no_match(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.search_result = SearchResult(
        query="revenue",
        mode="bm25",
        hits=(),
        coverage=_coverage(targets=(TargetVerdict("A9", False),)),
        not_in_corpus=("A9",),
    )
    result = operator.execute_by_id("local_search", session, {"query": "revenue"})
    assert result.data["not_in_corpus"] == ["A9"]
    assert result.data["no_match"] is False


def test_local_search_no_match_is_distinguishable(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.search_result = SearchResult(
        query="revenue", mode="bm25", hits=(), coverage=_coverage()
    )
    result = operator.execute_by_id("local_search", session, {"query": "revenue"})
    assert result.data["not_in_corpus"] == []
    assert result.data["no_match"] is True


def test_local_search_seed_and_intersect(tmp_path) -> None:
    session, _ = _session(tmp_path)
    seeded = operator.execute_by_id(
        "local_search_seed", session, {"query": "revenue", "into": "hits"}
    )
    assert seeded.error_code is None
    assert session.sets["hits"].accessions == frozenset({"A1", "A2"})
    session.add_set("main", ["A1", "A3"])
    narrowed = operator.execute_by_id(
        "local_search_seed",
        session,
        {"query": "revenue", "into": "main", "action": "intersect"},
    )
    assert narrowed.error_code is None
    assert narrowed.data["base_count"] == 2
    assert session.sets["main"].accessions == frozenset({"A1"})


def test_efts_gatherers_prompt_each_bool_once(tmp_path, monkeypatch) -> None:
    session, _ = _session(tmp_path)
    confirms: list[str] = []
    monkeypatch.setattr(
        operator_selection, "prompt_text", lambda prompt, default="": default
    )

    def fake_confirm(prompt, default=False):
        confirms.append(prompt)
        return True

    monkeypatch.setattr(operator_selection, "prompt_confirm", fake_confirm)
    search = operator_tools.GATHERERS["efts_search"](session)
    assert confirms == ["exhaustive retrieval?"]
    assert search.exhaustive is True
    confirms.clear()
    capture = operator_tools.GATHERERS["efts_capture"](session)
    assert confirms == ["exhaustive capture?", "capture this search to disk?"]
    assert capture.exhaustive is True
    assert capture.confirm is True


def test_local_search_seed_refuses_unknown_action(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id(
        "local_search_seed", session, {"query": "revenue", "action": "union"}
    )
    assert result.error_code == "invalid_options"
