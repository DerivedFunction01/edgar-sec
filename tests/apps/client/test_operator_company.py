"""Tests for the operator's company rows and frames cross-check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from edgar_sec.apps.client import operator, operator_company, operator_run_records
from edgar_sec.apps.client.concept import ConceptResult
from edgar_sec.apps.client.frames import FrameIdentity, FrameResult, FrameRow
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik


def _acc(number: int) -> str:
    return f"{number:010d}-24-{number:06d}"


def _result(tmp_path: Path, rows: list[tuple[int, str]]) -> FilingsResult:
    cik = Cik.from_raw(320193)
    items = tuple(
        FilingAggregate(
            accession=AccessionNumber.from_any(_acc(number)),
            primary_cik=cik,
            ciks=(cik,),
            form=form,
            filing_date=f"2024-01-{number:02d}",
        )
        for number, form in rows
    )
    return FilingsResult(
        run_id="run-x",
        plan_id="plan-x",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=items,
    )


class _FakeCompany:
    """Company stand-in with canned filings, concept values, and xbrl."""

    def __init__(
        self, tmp_path: Path, name: str, cik: int, *, fail_filings: bool = False
    ) -> None:
        self.profile = SimpleNamespace(cik=Cik(cik), name=name)
        self.name = name
        self.tickers = ("ACME",)
        self.sic = "3571"
        self.sic_description = "Electronic Computers"
        self.state_of_incorporation = "DE"
        self.fiscal_year_end = "1231"
        self._tmp_path = tmp_path
        self._fail_filings = fail_filings
        self.concept_values = (
            ConceptResult(
                value=100,
                unit="USD",
                end="2024-12-31",
                accession=_acc(1),
                form="10-K",
                filed="2025-02-01",
                fiscal_year=2024,
                fiscal_period="FY",
                frame="CY2024",
            ),
        )

    @property
    def cik(self) -> Cik:
        return self.profile.cik

    def filings(self, forms=None, *, limit=None, dates=None):
        if self._fail_filings:
            raise RuntimeError("filings backend unavailable")
        return _result(self._tmp_path, [(1, "10-K"), (2, "10-Q")])

    def concept(self, taxonomy: str, tag: str):
        return self.concept_values

    def xbrl(self, form=None):
        return SimpleNamespace(financials=object())


class _FakeFacade:
    """Facade stand-in: direct resolutions, a placeholder, name candidates."""

    def __init__(self, tmp_path: Path) -> None:
        self.artifacts_root = tmp_path
        self.calls: list[str] = []
        self.acme = _FakeCompany(tmp_path, "Acme Anvils Inc", 111)
        self.apple = _FakeCompany(tmp_path, "Apple Inc", 320193)
        self.broken = _FakeCompany(tmp_path, "Broken Co", 999, fail_filings=True)
        self.companies = {
            "111": self.acme,
            "320193": self.apple,
            "999": self.broken,
        }
        self.candidate_entries: list[dict] = [
            {"name": "Acme Anvils Inc", "cik": "111", "tickers": ["ACME"]},
            {"name": "Acme Rockets Inc", "cik": "222", "tickers": []},
            {"name": "Globex Corporation", "cik": "333", "tickers": ["GLBX"]},
        ]
        identity = FrameIdentity("us-gaap", "Assets", "USD", "CY2024Q4I")
        self.frame_result = FrameResult(
            frame=identity,
            label="Assets",
            rows=tuple(
                FrameRow(
                    cik=100 + n,
                    entity_name=f"Entity {n}",
                    value=n * 10,
                    end="2024-12-31",
                    frame=identity,
                )
                for n in range(3)
            ),
        )

    def company(self, identifier):
        self.calls.append(str(identifier))
        found = self.companies.get(str(identifier))
        if found is not None:
            return found
        if str(identifier) == "AAPL":
            return self.apple
        if str(identifier) == "BRKN":
            return self.broken
        profile = SimpleNamespace(cik=Cik(1), name=str(identifier))
        return SimpleNamespace(profile=profile, name=str(identifier))

    def company_candidates(self, query):
        return list(self.candidate_entries)

    def frames(self, taxonomy, tag, unit, period):
        self.calls.append(f"frames:{taxonomy}:{tag}")
        return self.frame_result

    def cache_stats(self):
        return {"responses": {"entries": 3}}


def _session(tmp_path: Path) -> tuple[operator.ClientSession, _FakeFacade]:
    facade = _FakeFacade(tmp_path)
    return operator.ClientSession(facade=facade), facade


def test_company_and_frames_effects() -> None:
    assert operator.REGISTRY["company"].effect == "reads_state"
    assert operator.REGISTRY["company_filings"].effect == "reads_state"
    assert operator.REGISTRY["company_concept"].effect == "reads_state"
    assert operator.REGISTRY["frames"].effect == "external"


def test_help_examples_name_a_tag_and_duration_period() -> None:
    from edgar_sec.apps.client.operator_discovery import operation_help

    concept = operation_help(operator.REGISTRY["company_concept"])
    tag_help = next(f["help"] for f in concept["options"] if f["name"] == "tag")
    assert "Revenues" in tag_help
    frames = operation_help(operator.REGISTRY["frames"])
    frame_tag = next(f["help"] for f in frames["options"] if f["name"] == "tag")
    period = next(f["help"] for f in frames["options"] if f["name"] == "period")
    assert "Revenues" in frame_tag
    assert "CY2024" in period
    assert "CY2024Q4I" in period


def test_scoring_exact_and_clear_winner() -> None:
    entries = [
        {"name": "Acme Anvils Inc", "cik": "111", "tickers": []},
        {"name": "Acme Rockets Inc", "cik": "222", "tickers": []},
    ]
    scored = operator_company.score_name_candidates("Acme Anvils", entries)
    assert scored[0]["cik"] == "111"
    assert scored[0]["score"] >= 0.98
    assert scored[0]["score"] - scored[1]["score"] >= 0.15


def test_company_ticker_resolves_directly(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"identifier": "AAPL", "include": ["profile"]}
    result = operator.execute_by_id("company", session, options)
    assert result.error_code is None
    assert result.data["resolution"]["via"] == "ticker"
    assert result.data["sections"]["profile"]["status"] == "ok"
    assert result.data["sections"]["profile"]["cik"] == "0000320193"


def test_company_cik_resolves_directly(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"identifier": "320193", "include": ["profile"]}
    result = operator.execute_by_id("company", session, options)
    assert result.data["resolution"]["via"] == "cik"
    assert result.data["company"]["name"] == "Apple Inc"


def test_company_exact_name_resolves_with_candidates(tmp_path) -> None:
    session, facade = _session(tmp_path)
    options = {"identifier": "Acme Anvils", "include": ["profile"]}
    result = operator.execute_by_id("company", session, options)
    assert result.error_code is None
    assert result.data["resolution"]["via"] == "name"
    candidates = result.data["resolution"]["candidates"]
    assert candidates[0]["name"] == "Acme Anvils Inc"
    assert candidates[0]["score"] >= 0.98
    assert "111" in facade.calls
    assert result.data["company"]["cik"] == "0000000111"


def test_company_near_tie_refuses_with_scored_candidates(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.candidate_entries = [
        {"name": "Acme Alpha Inc", "cik": "111", "tickers": []},
        {"name": "Acme Beta Inc", "cik": "222", "tickers": []},
    ]
    result = operator.execute_by_id("company", session, {"identifier": "Acme"})
    assert result.error_code == "refused"
    candidates = result.data["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["score"] == candidates[1]["score"]
    assert all("score" in candidate for candidate in candidates)


def test_company_unknown_name_is_not_a_placeholder(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.candidate_entries = []
    options = {"identifier": "Nonexistent Name"}
    result = operator.execute_by_id("company", session, options)
    assert result.error_code == "not_found"
    assert result.data["candidates"] == []
    assert "sections" not in result.data


def _write_catalog_snapshot(artifacts_root: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    snapshots_root = artifacts_root / "filing_catalog" / "snapshots"
    snapshot_dir = snapshots_root / "snap-test"
    snapshot_dir.mkdir(parents=True)
    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("identity", pa.struct([("name", pa.string())])),
            (
                "listings",
                pa.list_(
                    pa.struct([("ticker", pa.string()), ("exchange", pa.string())])
                ),
            ),
        ]
    )
    rows = [
        {
            "cik": "0000320193",
            "identity": {"name": "Apple Inc"},
            "listings": [{"ticker": "AAPL", "exchange": "Nasdaq"}],
        },
        {
            "cik": "0000111111",
            "identity": {"name": "American Alpha Inc"},
            "listings": [{"ticker": "AMAL", "exchange": "NYSE"}],
        },
        {
            "cik": "0000222222",
            "identity": {"name": "American Beta Inc"},
            "listings": [{"ticker": "AMBE", "exchange": "NYSE"}],
        },
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, snapshot_dir / "company_profiles.parquet")
    second_dir = snapshots_root / "snap-test-2"
    second_dir.mkdir(parents=True)
    pq.write_table(table, second_dir / "company_profiles.parquet")


class _ProductionShapeFacade:
    """Real Edgar shape: artifacts_root None, no candidate providers."""

    def __init__(self, tmp_path: Path) -> None:
        self.artifacts_root = None
        self.calls: list[str] = []
        self.apple = _FakeCompany(tmp_path, "Apple Inc", 320193)
        self.alpha = _FakeCompany(tmp_path, "American Alpha Inc", 111111)
        self.beta = _FakeCompany(tmp_path, "American Beta Inc", 222222)
        self.companies = {
            "320193": self.apple,
            "0000320193": self.apple,
            "111111": self.alpha,
            "0000111111": self.alpha,
            "222222": self.beta,
            "0000222222": self.beta,
        }

    def company(self, identifier):
        self.calls.append(str(identifier))
        found = self.companies.get(str(identifier))
        if found is not None:
            return found
        if str(identifier) == "AAPL":
            return self.apple
        profile = SimpleNamespace(cik=Cik(1), name=str(identifier))
        return SimpleNamespace(profile=profile, name=str(identifier))


def _production_session(tmp_path, monkeypatch):
    artifacts_root = tmp_path / "artifacts"
    _write_catalog_snapshot(artifacts_root)
    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.paths.resolve_paths",
        lambda: SimpleNamespace(artifacts_root=artifacts_root),
    )
    facade = _ProductionShapeFacade(tmp_path)
    return operator.ClientSession(facade=facade), facade


def test_company_name_resolves_from_catalog_when_facade_root_is_none(
    tmp_path, monkeypatch
) -> None:
    session, facade = _production_session(tmp_path, monkeypatch)
    assert facade.artifacts_root is None
    assert not hasattr(facade, "company_candidates")
    assert not hasattr(facade, "name_candidates")
    assert not hasattr(facade, "company_name_candidates")
    options = {"identifier": "Apple", "include": ["profile"]}
    result = operator.execute_by_id("company", session, options)
    assert result.error_code is None
    assert result.data["resolution"]["via"] == "name"
    candidates = result.data["resolution"]["candidates"]
    assert [c["name"] for c in candidates].count("Apple Inc") == 1
    assert candidates[0]["name"] == "Apple Inc"
    assert candidates[0]["cik"] == "0000320193"
    assert candidates[0]["score"] >= 0.6
    assert result.data["company"]["cik"] == "0000320193"
    assert result.data["company"]["name"] == "Apple Inc"


def test_company_ambiguous_name_refuses_from_catalog_when_root_is_none(
    tmp_path, monkeypatch
) -> None:
    session, facade = _production_session(tmp_path, monkeypatch)
    assert facade.artifacts_root is None
    result = operator.execute_by_id("company", session, {"identifier": "American"})
    assert result.error_code == "refused"
    candidates = result.data["candidates"]
    assert len(candidates) >= 2
    names = {candidate["name"] for candidate in candidates[:2]}
    assert names == {"American Alpha Inc", "American Beta Inc"}
    assert candidates[0]["score"] == candidates[1]["score"]


def test_company_composite_accounts_a_failing_section(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("company", session, {"identifier": "BRKN"})
    assert result.error_code is None
    sections = result.data["sections"]
    assert sections["profile"]["status"] == "ok"
    assert sections["financials"]["status"] == "ok"
    assert sections["financials"]["available"] is True
    assert sections["recent_filings"]["status"] == "error"
    assert sections["recent_filings"]["error_code"] == "external_failure"


def test_company_include_is_a_closed_set(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"identifier": "AAPL", "include": ["bogus"]}
    result = operator.execute_by_id("company", session, options)
    assert result.error_code == "invalid_options"


def test_company_filings_row_seeds_a_named_set(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"identifier": "AAPL", "into": "apple"}
    result = operator.execute_by_id("company_filings", session, options)
    assert result.error_code is None
    assert (result.total, result.shown) == (2, 2)
    assert result.data["set"] == "apple"
    assert len(session.sets["apple"]) == 2


def test_company_concept_values_as_returned(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {"identifier": "AAPL", "taxonomy": "us-gaap", "tag": "Assets"}
    result = operator.execute_by_id("company_concept", session, options)
    assert result.error_code is None
    assert result.data["provenance"] == "SEC-reported, exactly as reported"
    assert result.data["values"][0]["value"] == 100
    assert result.data["values"][0]["frame"] == "CY2024"
    assert (result.total, result.shown) == (1, 1)


def test_company_concept_empty_is_absent(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.apple.concept_values = ()
    options = {"identifier": "AAPL", "taxonomy": "us-gaap", "tag": "Assets"}
    result = operator.execute_by_id("company_concept", session, options)
    assert result.error_code == "absent"
    assert result.data["present"] is False


def test_company_concept_needs_explicit_coordinates(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("company_concept", session, {"identifier": "AAPL"})
    assert result.error_code == "invalid_options"


def test_frames_labelled_cross_check_and_recorded(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "unit": "USD",
        "period": "CY2024Q4I",
        "limit": 2,
    }
    result = operator.execute_by_id("frames", session, options)
    assert result.error_code is None
    assert "cross-check" in result.title
    assert result.data["cross_check"] is True
    assert result.data["provenance"] == "SEC frame aggregates"
    assert (result.total, result.shown) == (3, 2)
    records = operator_run_records.list_records(session)
    assert len(records) == 1
    assert records[0]["operation"] == "frames"
    assert records[0]["selection"]["tag"] == "Assets"


def test_frames_absent_frame_is_honest_absence(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.frame_result = FrameResult(
        frame=FrameIdentity("us-gaap", "Assets", "USD", "CY2024Q4I"),
        label="",
        rows=(),
    )
    options = {
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "unit": "USD",
        "period": "CY2024Q4I",
    }
    result = operator.execute_by_id("frames", session, options)
    assert result.error_code == "absent"
    assert result.data["present"] is False
    assert "cross-check" in result.title


def test_frames_needs_explicit_coordinates(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("frames", session, {"taxonomy": "us-gaap"})
    assert result.error_code == "invalid_options"
    assert operator_run_records.list_records(session) == []
