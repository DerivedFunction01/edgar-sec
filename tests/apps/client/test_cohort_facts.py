"""Tests pinning cohort-sourced fact sets against loaded facades."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortFact, CohortFactMatch
from edgar_sec.engine.xbrl.solve.concept_table import (
    CohortEntry,
    build_cohort_table,
)
from edgar_sec.engine.xbrl.solve.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.storage.storage import (
    declarations_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.infra.storage.dag.publication import publish_node
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.xbrl_review.bundles import (
    load_filing,
    registry_filings,
    registry_row,
)
from edgar_sec.pipelines.xbrl_review.commands.project import project_xbrl_run
from edgar_sec.pipelines.xbrl_review.execution import execute_projection_run
from edgar_sec.pipelines.xbrl_review.paths import xbrl_paths
from edgar_sec.pipelines.xbrl_review.schemas import (
    CALCULATION_ARCS_SCHEMA,
    PRESENTATION_ARCS_SCHEMA,
    SOLVED_NODES_SCHEMA,
)
from tests.engine.xbrl.solve.conftest import load_seed_cohort
from tests.support import fixture_path


def _load_bundle(folder: str) -> FilingXbrl:
    root = fixture_path(f"xbrl/seed/{folder}")
    facts = tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=(
                row["numeric_value"]
                if row["numeric_value"] is not None
                else row["text_value"]
            ),
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in pq.read_table(root / "facts.parquet").to_pylist()
    )
    arcs = tuple(
        CalculationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            weight=row["weight"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in pq.read_table(root / "calculation_arcs.parquet").to_pylist()
    )
    declarations = declarations_from_arrow_table(
        read_declarations_parquet(root / "declarations.parquet")
    )
    return FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, declarations=declarations),
    )


@pytest.fixture(scope="module")
def cohort() -> tuple:
    """Entries plus the concept table carrying the cohort's declarations."""
    taxonomy = load_domain_taxonomy()
    entries = load_seed_cohort()
    merged: dict[str, object] = {}
    for entry in entries:
        path = entry.facts_path.parent / "declarations.parquet"
        if path.exists():
            for decl in declarations_from_arrow_table(read_declarations_parquet(path)):
                merged[decl.concept_qname] = decl
    table = build_cohort_table(taxonomy, entries, declarations=tuple(merged.values()))
    return taxonomy, entries, table


def _fact_key(fact: XbrlFact) -> tuple:
    return (
        fact.concept_qname,
        repr(fact.value),
        fact.unit,
        fact.period_type,
        fact.start_date,
        fact.end_date,
        fact.instant_date,
        json.dumps(fact.dimensions, sort_keys=True),
    )


@pytest.mark.parametrize(
    "firm,folder",
    [("MSFT", "msft_2024_10k"), ("V", "v_2024_10k"), ("ALL_2022", "all_2022_2022_10k")],
)
def test_from_cohort_agrees_with_loaded(cohort, firm: str, folder: str) -> None:
    """Verify indexed fact sets match loaded sets: count, facts, atoms."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == firm)
    loaded = Xbrl(_load_bundle(folder), taxonomy)
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    assert len(indexed.facts) == len(loaded.facts)
    assert sorted(_fact_key(f) for f in indexed.facts) == sorted(
        _fact_key(f) for f in loaded.facts
    )
    for qname, record in loaded.facts.records.items():
        other = indexed.facts.records[qname]
        assert (other.atom.head, other.atom.modifiers) == (
            record.atom.head,
            record.atom.modifiers,
        )


def test_from_cohort_query_battery_matches_loaded(cohort) -> None:
    """Verify census-style queries answer identically from indexed sets."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    loaded = Xbrl(_load_bundle("msft_2024_10k"), taxonomy)
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    for term in ("revenue", "cfo", "us-gaap:Assets", "Net Income"):
        for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
            want = loaded.query(term, mode=mode, fiscal_year=2024)
            got = indexed.query(term, mode=mode, fiscal_year=2024)
            assert (got.status, got.value) == (want.status, want.value)


def test_from_cohort_carries_the_filings_evidence_record(cohort) -> None:
    """Verify a cohort facade carries its own filing's evidence record."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "AAPL")
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    record = indexed.evidence
    assert record is not None
    assert record.accession == entry.accession and record.firm == "AAPL"
    payables = record.entry("us-gaap:AccountsPayableCurrent")
    assert payables is not None
    assert payables.placement_horizon == "M_CURRENT"
    assert payables.attested_placed
    loaded = Xbrl(_load_bundle("aapl_2024_10k"), taxonomy)
    assert loaded.evidence is None


def test_from_cohort_unknown_accession_raises(cohort) -> None:
    """Verify an accession outside the cohort entries is refused."""
    _taxonomy, entries, table = cohort
    with pytest.raises(ValueError, match="not among cohort entries"):
        Xbrl.from_cohort(table, entries, "0000000000-00-000000")


def test_from_lookup_records_carry_tier_and_rule(cohort) -> None:
    """Verify lookup-sourced records carry tier/rule and project facts."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    record = table.record("us-gaap:NetCashProvidedByUsedInOperatingActivities")
    match = CohortFactMatch(
        accession=entry.accession,
        firm="MSFT",
        qname=record.qname,
        atom=record.atom,
        tier="EXACT",
        rule="identity",
        direction="SAME",
        via_default=False,
        fact=CohortFact(
            accession=entry.accession,
            qname=record.qname,
            value=118_548_000_000.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
        compatible=True,
    )
    facade = Xbrl.from_lookup(table, [match], entry.accession)
    assert len(facade.facts) == 1
    fact = facade.facts[0]
    assert fact.value == 118_548_000_000.0
    assert fact.dimensions == {}  # display projection: no dimensions
    display = facade.facts.records[record.qname]
    assert display.tier == "EXACT"
    assert display.rule == "identity"
    assert display.atom == record.atom
    assert display.residual_mass == (record.residual_intent, record.residual_total)


def test_from_lookup_filters_other_accessions(cohort) -> None:
    """Verify from_lookup keeps only the requested accession's matches."""
    _taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    record = table.record("us-gaap:Assets")

    def make_match(accession: str) -> CohortFactMatch:
        return CohortFactMatch(
            accession=accession,
            firm="X",
            qname=record.qname,
            atom=record.atom,
            tier="EXACT",
            rule="identity",
            direction="SAME",
            via_default=False,
            fact=CohortFact(
                accession=accession,
                qname=record.qname,
                value=1.0,
                unit="USD",
                period_type="instant",
                instant_date="2024-06-30",
            ),
            compatible=True,
        )

    facade = Xbrl.from_lookup(
        table,
        [make_match(entry.accession), make_match("9999999999-99-999999")],
        entry.accession,
    )
    assert len(facade.facts) == 1


_SNAPSHOT_ACCESSION = "0000320193-24-000123"
_SNAPSHOT_ID = "snapshot-test8b00000001"
_ROLE = "http://www.xbrl.org/2003/role/balanceSheet"


def _snapshot_nodes() -> list[dict]:
    base = {
        "accession": _SNAPSHOT_ACCESSION,
        "firm": "TEST",
        "cik": 320193,
        "resolution_tier": "ATOM",
        "derived_value": None,
        "derivation_path": "",
        "latency_ms": 1.0,
    }
    return [
        {
            **base,
            "concept_qname": "us-gaap:Assets",
            "period": "2024-09-28",
            "prime_head": "H_ASSET",
            "modifiers_json": '["M_TOTAL"]',
            "reported_value": 352_583_000_000.0,
        },
        {
            **base,
            "concept_qname": "us-gaap:NetIncomeLoss",
            "period": "2024-09-28",
            "prime_head": "H_INCOME",
            "modifiers_json": '["M_NET"]',
            "reported_value": 93_736_000_000.0,
        },
    ]


def _publish_fabricated_snapshot(
    tmp_path: Path, *, with_arcs: bool, nodes: list[dict] | None = None
) -> str:
    """Publish one checkpoint snapshot carrying the fabricated nodes."""
    paths = xbrl_paths(tmp_path)
    staged = tmp_path / "stage"
    relations: dict[str, tuple[PartDescriptor, ...]] = {}

    def stage(name: str, rows: list[dict], schema: pa.Schema) -> None:
        relation_dir = staged / name
        relation_dir.mkdir(parents=True, exist_ok=True)
        part = relation_dir / "part-00000.parquet"
        write_parquet_table(pa.Table.from_pylist(rows, schema=schema), part)
        relations[name] = (
            PartDescriptor(
                path=f"{name}/part-00000.parquet",
                sha256=file_sha256(part),
                row_count=len(rows),
                byte_size=part.stat().st_size,
            ),
        )

    stage("solved_nodes", nodes or _snapshot_nodes(), SOLVED_NODES_SCHEMA)
    if with_arcs:
        stage(
            "presentation_arcs",
            [
                {
                    "accession": _SNAPSHOT_ACCESSION,
                    "parent_qname": "us-gaap:Assets",
                    "child_qname": "us-gaap:AssetsCurrent",
                    "order": 1.0,
                    "role_uri": _ROLE,
                }
            ],
            PRESENTATION_ARCS_SCHEMA,
        )
        stage(
            "calculation_arcs",
            [
                {
                    "accession": _SNAPSHOT_ACCESSION,
                    "parent_qname": "us-gaap:Assets",
                    "child_qname": "us-gaap:AssetsCurrent",
                    "weight": 1.0,
                    "order": 1.0,
                    "role_uri": _ROLE,
                }
            ],
            CALCULATION_ARCS_SCHEMA,
        )
    manifest = DAGNodeManifest(
        snapshot_id=_SNAPSHOT_ID,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=_SNAPSHOT_ID,
        lineage_depth=0,
        created_at="2026-10-28T00:00:00+00:00",
        relations=relations,
        logical_fingerprint="test8b",
    )
    publish_node(paths.snapshots_root, manifest, staged_dir=staged, branch_name="main")
    return _SNAPSHOT_ID


def test_from_snapshot_builds_projection_facade(tmp_path: Path) -> None:
    """Verify snapshot facts, periods, cik, records, and arcs are carried."""
    snapshot_id = _publish_fabricated_snapshot(tmp_path, with_arcs=True)
    facade = Xbrl.from_snapshot(tmp_path, snapshot_id, _SNAPSHOT_ACCESSION)
    assert facade.cik == "0000320193"
    assert len(facade.facts) == 2
    by_qname = {fact.concept_qname: fact for fact in facade.facts}
    assets = by_qname["us-gaap:Assets"]
    assert assets.value == 352_583_000_000.0
    assert assets.period_type == "instant"
    assert assets.instant_date == "2024-09-28"
    assert assets.unit is None and assets.dimensions == {}
    income = by_qname["us-gaap:NetIncomeLoss"]
    assert income.period_type == "duration"
    assert income.end_date == "2024-09-28"
    record = facade.facts.records["us-gaap:Assets"]
    assert record.atom.head == "H_ASSET"
    assert record.atom.modifiers == frozenset({"M_TOTAL"})
    assert record.presumed_atom == record.atom
    assert facade.linkbases is not None
    assert facade.linkbases.presentation_arcs == (
        PresentationArc(
            parent_qname="us-gaap:Assets",
            child_qname="us-gaap:AssetsCurrent",
            order=1.0,
            role_uri=_ROLE,
        ),
    )
    assert facade.linkbases.calculation_arcs == (
        CalculationArc(
            parent_qname="us-gaap:Assets",
            child_qname="us-gaap:AssetsCurrent",
            weight=1.0,
            order=1.0,
            role_uri=_ROLE,
        ),
    )


def test_from_snapshot_tolerates_pre_arc_snapshots(tmp_path: Path) -> None:
    """Verify a snapshot without arc relations reads both arc kinds empty."""
    snapshot_id = _publish_fabricated_snapshot(tmp_path, with_arcs=False)
    facade = Xbrl.from_snapshot(tmp_path, snapshot_id, _SNAPSHOT_ACCESSION)
    assert len(facade.facts) == 2
    assert facade.linkbases is not None
    assert facade.linkbases.presentation_arcs == ()
    assert facade.linkbases.calculation_arcs == ()


def test_from_snapshot_unknown_accession_and_snapshot_raise(tmp_path: Path) -> None:
    """Verify unknown accessions and snapshot ids are refused."""
    snapshot_id = _publish_fabricated_snapshot(tmp_path, with_arcs=True)
    with pytest.raises(ValueError, match="not in snapshot"):
        Xbrl.from_snapshot(tmp_path, snapshot_id, "0000000000-00-000000")
    with pytest.raises(ValueError, match="not found"):
        Xbrl.from_snapshot(tmp_path, "snapshot-missing000000", _SNAPSHOT_ACCESSION)


def test_from_snapshot_records_come_from_table_when_given(
    tmp_path: Path, cohort
) -> None:
    """Verify a supplied concept table supplies the display records."""
    _taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    nodes = [
        {
            **row,
            "accession": entry.accession,
            "concept_qname": "us-gaap:Assets",
            "period": "2024-06-30",
        }
        for row in _snapshot_nodes()[:1]
    ]
    paths = xbrl_paths(tmp_path)
    staged = tmp_path / "stage"
    relation_dir = staged / "solved_nodes"
    relation_dir.mkdir(parents=True)
    part = relation_dir / "part-00000.parquet"
    write_parquet_table(pa.Table.from_pylist(nodes, schema=SOLVED_NODES_SCHEMA), part)
    manifest = DAGNodeManifest(
        snapshot_id=_SNAPSHOT_ID,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=_SNAPSHOT_ID,
        lineage_depth=0,
        created_at="2026-10-28T00:00:00+00:00",
        relations={
            "solved_nodes": (
                PartDescriptor(
                    path="solved_nodes/part-00000.parquet",
                    sha256=file_sha256(part),
                    row_count=len(nodes),
                    byte_size=part.stat().st_size,
                ),
            )
        },
        logical_fingerprint="test8b-table",
    )
    publish_node(paths.snapshots_root, manifest, staged_dir=staged, branch_name="main")
    facade = Xbrl.from_snapshot(tmp_path, _SNAPSHOT_ID, entry.accession, table=table)
    expected = table.record("us-gaap:Assets")
    record = facade.facts.records["us-gaap:Assets"]
    assert record.atom == expected.atom
    assert record.presumed_atom == expected.presumed_atom


def test_from_snapshot_published_arcs_match_bundles(tmp_path: Path) -> None:
    """Verify a real published snapshot's arcs row-match the source bundles."""
    seeds = [s for s in registry_filings() if s.firm in ("MCD", "EOG")]
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps([registry_row(seed) for seed in seeds]), encoding="utf-8"
    )
    manifest = project_xbrl_run(
        dataset_path=dataset, artifacts_root=tmp_path, chunk_size=1
    )
    result = execute_projection_run(str(manifest["run_id"]), artifacts_root=tmp_path)
    seed = next(s for s in seeds if s.firm == "MCD")
    loaded = load_filing(seed)
    facade = Xbrl.from_snapshot(tmp_path, result.snapshot_id, str(seed.accession))
    assert facade.linkbases is not None

    def arc_key(arc: object) -> tuple:
        return (
            arc.parent_qname,
            arc.child_qname,
            arc.order,
            arc.role_uri or "",
            getattr(arc, "weight", 0.0),
        )

    assert sorted(map(arc_key, facade.linkbases.presentation_arcs)) == sorted(
        map(arc_key, loaded.pres_arcs)
    )
    assert sorted(map(arc_key, facade.linkbases.calculation_arcs)) == sorted(
        map(arc_key, loaded.calc_arcs)
    )
    snapshot_dir = xbrl_paths(tmp_path).snapshots_root / result.snapshot_id
    nodes = pq.read_table(snapshot_dir / "solved_nodes" / "part-00000.parquet")
    own = [r for r in nodes.to_pylist() if r["accession"] == str(seed.accession)]
    assert len(facade.facts) == len(own)
    values = {fact.concept_qname: fact.value for fact in facade.facts}
    for row in own:
        assert values[row["concept_qname"]] == row["reported_value"]


def test_from_snapshot_period_typing_without_declaration(tmp_path: Path) -> None:
    """Verify span labels read as durations and dateless single dates as instants."""
    base = _snapshot_nodes()[0]
    nodes = [
        {
            **base,
            "concept_qname": "test:InstantExtension",
            "period": "2024-09-28",
            "reported_value": 5.0,
        },
        {
            **base,
            "concept_qname": "test:DurationExtension",
            "period": "2023-10-01/2024-09-28",
            "reported_value": 7.0,
        },
    ]
    snapshot_id = _publish_fabricated_snapshot(tmp_path, with_arcs=False, nodes=nodes)
    facade = Xbrl.from_snapshot(tmp_path, snapshot_id, _SNAPSHOT_ACCESSION)
    by_qname = {fact.concept_qname: fact for fact in facade.facts}
    instant = by_qname["test:InstantExtension"]
    assert instant.period_type == "instant"
    assert instant.instant_date == "2024-09-28"
    duration = by_qname["test:DurationExtension"]
    assert duration.period_type == "duration"
    assert duration.start_date == "2023-10-01"
    assert duration.end_date == "2024-09-28"


def test_from_snapshot_parity_with_bundle_facade(tmp_path: Path) -> None:
    """Verify snapshot and bundle facades agree on the projection surface."""
    seeds = [s for s in registry_filings() if s.firm in ("AAPL", "MCD")]
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps([registry_row(seed) for seed in seeds]), encoding="utf-8"
    )
    manifest = project_xbrl_run(
        dataset_path=dataset, artifacts_root=tmp_path, chunk_size=1
    )
    result = execute_projection_run(str(manifest["run_id"]), artifacts_root=tmp_path)
    taxonomy = load_domain_taxonomy()
    scalars = (
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "operating_cash_flow",
        "capex",
        "free_cash_flow",
    )
    for seed in seeds:
        loaded = load_filing(seed)
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(str(seed.accession)),
            cik=Cik(int(seed.cik)),
            facts=loaded.facts,
            linkbases=LinkbaseBundle(
                calculation_arcs=loaded.calc_arcs,
                presentation_arcs=loaded.pres_arcs,
                declarations=tuple(loaded.declarations.values()),
            ),
        )
        base = Xbrl(bundle, taxonomy)
        snap = Xbrl.from_snapshot(tmp_path, result.snapshot_id, str(seed.accession))
        bundle_values: dict[str, set] = {}
        for fact in base.facts:
            bundle_values.setdefault(fact.concept_qname, set()).add(
                (fact.value, fact.instant_date or fact.end_date)
            )
        for fact in snap.facts:
            if fact.value is not None:
                assert (fact.value, fact.instant_date or fact.end_date) in (
                    bundle_values.get(fact.concept_qname, set())
                )
        if seed.firm != "AAPL":
            continue
        for term in ("revenue", "cfo", "us-gaap:Assets", "Net Income"):
            for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
                want = base.query(term, mode=mode, fiscal_year=seed.fy)
                got = snap.query(term, mode=mode, fiscal_year=seed.fy)
                assert (got.status, got.value) == (want.status, want.value)
        for name in scalars:
            assert getattr(snap.financials, name) == getattr(base.financials, name)
        for view in ("income_statement", "balance_sheet", "cash_flow_statement"):
            want = getattr(base.statements, view)().graph
            got = getattr(snap.statements, view)().graph
            for attr in (
                "gross_profit",
                "operating_income",
                "net_income",
                "total_assets",
                "total_liabilities",
                "total_equity",
                "cfo",
                "cfi",
                "cff",
            ):
                assert getattr(got, attr, None) == getattr(want, attr, None)


def test_visa_cfo_query_resolves_the_annual_reported_fact() -> None:
    """Verify Visa cfo answers from the annual period, not a stray span."""
    facade = Xbrl(_load_bundle("v_2024_10k"), load_domain_taxonomy())
    reported = facade.query("cfo", mode=QueryMode.REPORTED_ONLY, fiscal_year=2024)
    assert reported.status == QueryStatus.REPORTED
    assert reported.value == 19_950_000_000.0
    assert reported.candidate_qnames == (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    )
    verified = facade.query("cfo", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024)
    assert verified.value == 19_950_000_000.0
    operating = facade.query(
        "operating_income", mode=QueryMode.REPORTED_ONLY, fiscal_year=2024
    )
    assert operating.value == 23_595_000_000.0
    assert operating.candidate_qnames == ("us-gaap:OperatingIncomeLoss",)
    assert facade.financials.operating_cash_flow == 19_950_000_000.0


@pytest.mark.parametrize(
    "folder,artefact_qname,artefact_value",
    [
        (
            "jnj_2024_10k",
            "us-gaap:DeferredTaxAssetsOperatingLossCarryforwards",
            2_298_000_000.0,
        ),
        (
            "nem_2024_10k",
            "nem:DeferredTaxAssetsNetOperatingLossCapitalLossAndTaxCredits",
            2_297_000_000.0,
        ),
    ],
)
def test_operating_income_absent_filings_serve_no_artefact(
    folder: str, artefact_qname: str, artefact_value: float
) -> None:
    """Verify filings with no operating-income fact serve none.

    Each filing's only operating-atom candidate is an instant tax fact.
    """
    bundle = _load_bundle(folder)
    assert not any(
        fact.concept_qname == "us-gaap:OperatingIncomeLoss" for fact in bundle.facts
    )
    artefact = [fact for fact in bundle.facts if fact.concept_qname == artefact_qname]
    assert artefact and all(fact.period_type == "instant" for fact in artefact)
    assert artefact_value in [fact.value for fact in artefact]
    facade = Xbrl(bundle, load_domain_taxonomy())
    assert facade.financials.operating_income is None
    assert facade.financials.operating_income_series == {}


def test_jnj_operating_income_query_promotion_is_a_known_artefact() -> None:
    """Pin the query promotion: the instant tax fact, not operating income."""
    facade = Xbrl(_load_bundle("jnj_2024_10k"), load_domain_taxonomy())
    result = facade.query(
        "operating_income", mode=QueryMode.REPORTED_ONLY, fiscal_year=2024
    )
    assert result.candidate_qnames == (
        "us-gaap:DeferredTaxAssetsOperatingLossCarryforwards",
    )
    assert result.value == 2_298_000_000.0
