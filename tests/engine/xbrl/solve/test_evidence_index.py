"""Tests for filing-local evidence records and the evidence index."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.engine.xbrl.solve.concept_table import (
    CohortEntry,
    ConceptTable,
    build_cohort_table,
    build_concept_table,
)
from edgar_sec.engine.xbrl.solve.evidence_index import (
    EvidenceIndex,
    build_evidence_index,
    build_filing_evidence,
)
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)
from tests.engine.xbrl.solve.conftest import load_seed_cohort

_ACC = "0000000001-24-000001"
_ROLE = "http://example.com/role/STATEMENT"


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


@pytest.fixture(scope="module")
def seed_index(taxonomy: DomainTaxonomy) -> EvidenceIndex:
    """The seed cohort's evidence index, built over its concept table."""
    entries = load_seed_cohort()
    return build_evidence_index(entries, build_cohort_table(taxonomy, entries))


@pytest.fixture(scope="module")
def seed_entries() -> dict[str, CohortEntry]:
    return {entry.firm: entry for entry in load_seed_cohort()}


def test_seed_build_is_deterministic(
    taxonomy: DomainTaxonomy, seed_index: EvidenceIndex
) -> None:
    """Two builds of the seed cohort produce identical canonical records."""
    entries = load_seed_cohort()
    again = build_evidence_index(entries, build_cohort_table(taxonomy, entries))
    assert len(seed_index) == len(entries) == len(again)
    for accession, record in seed_index.records.items():
        assert record.canonical() == again.records[accession].canonical()
        assert record.concept_count == len(record.concepts)


def test_fcx_impairment_attested_placed(
    seed_index: EvidenceIndex, seed_entries: dict[str, CohortEntry]
) -> None:
    """FCX's impairment concept is reported and placed, arcs verbatim."""
    entry = seed_index.entry(
        seed_entries["FCX"].accession, "us-gaap:ImpairmentOfOilAndGasProperties"
    )
    assert entry is not None
    assert entry.reported and entry.attested_placed
    assert entry.fact_count == 3
    assert entry.period_types == ("duration",)
    assert entry.pres_parents == (
        (
            "us-gaap:AdjustmentsToReconcileNetIncomeLossToCashProvidedByUsedIn"
            "OperatingActivitiesAbstract",
            "http://www.fcx.com/role/CONSOLIDATEDSTATEMENTSOFCASHFLOWS",
            13.0,
        ),
    )
    assert entry.calc_parents == (
        (
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            1.0,
            "http://www.fcx.com/role/CONSOLIDATEDSTATEMENTSOFCASHFLOWS",
        ),
    )
    assert entry.calc_parent_heads == ("H_CASH",)


def test_msft_impairment_calc_weight_is_signed(
    seed_index: EvidenceIndex, seed_entries: dict[str, CohortEntry]
) -> None:
    """MSFT's impairment concept keeps its negative calc weight verbatim."""
    entry = seed_index.entry(
        seed_entries["MSFT"].accession, "msft:ImpairmentOfEquityInvestments"
    )
    assert entry is not None
    assert entry.reported and entry.attested_placed
    assert entry.fact_count == 3
    assert entry.calc_parents == (
        (
            "us-gaap:GainLossOnInvestments",
            -1.0,
            "http://www.microsoft.com/20240630/taxonomy/role/"
            "Role_DisclosureNetRecognizedGainsLossesOnEquityInvestmentsDetail",
        ),
    )
    assert entry.pres_parents[0][0].startswith(
        "us-gaap:ScheduleOfGainLossOnInvestments"
    )


def test_aapl_payables_placement_blocks_verbatim(
    seed_index: EvidenceIndex, seed_entries: dict[str, CohortEntry]
) -> None:
    """AAPL AccountsPayableCurrent blocks match its bundle's arcs verbatim."""
    entry = seed_index.entry(
        seed_entries["AAPL"].accession, "us-gaap:AccountsPayableCurrent"
    )
    assert entry is not None
    role = "http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS"
    assert entry.pres_parents == (("us-gaap:LiabilitiesCurrentAbstract", role, 1.0),)
    assert entry.pres_children == ()
    assert entry.calc_parents == (("us-gaap:LiabilitiesCurrent", 1.0, role),)
    assert entry.calc_children == ()
    assert entry.pres_roles == (role,)
    assert entry.declaration == ("xbrli:monetaryItemType", None, None, None)
    assert entry.period_types == ("instant",)
    assert entry.fact_count == 2
    assert entry.reported_undimensioned


def test_absence_is_silence(seed_index: EvidenceIndex) -> None:
    """Unknown accessions and qnames return None, never an empty record."""
    assert seed_index.entry("0000000000-00-000000", "us-gaap:Assets") is None
    some = next(iter(seed_index.records))
    assert seed_index.entry(some, "us-gaap:NoSuchConceptAnywhere") is None
    assert seed_index.record("0000000000-00-000000") is None


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _bundle(
    tmp_path: Path,
    *,
    accession: str = _ACC,
    facts: list[dict] | None = None,
    pres: list[dict] | None = None,
    calc: list[dict] | None = None,
) -> CohortEntry:
    folder = tmp_path / "bundle"
    _write_parquet(
        folder / "facts.parquet",
        facts
        if facts is not None
        else [
            {
                "accession": accession,
                "concept_qname": "us-gaap:AccountsPayableCurrent",
                "dimensions_json": "{}",
                "period_type": "instant",
            }
        ],
    )
    if pres is not None:
        _write_parquet(folder / "presentation_arcs.parquet", pres)
    if calc is not None:
        _write_parquet(folder / "calculation_arcs.parquet", calc)
    return CohortEntry(
        accession=accession, facts_path=folder / "facts.parquet", firm="TST"
    )


def _small_table(taxonomy: DomainTaxonomy) -> ConceptTable:
    return build_concept_table(taxonomy, ["us-gaap:AccountsPayableCurrent"])


def test_refuses_accession_mismatch(taxonomy: DomainTaxonomy, tmp_path: Path) -> None:
    """A bundle whose facts accession disagrees with its entry is refused."""
    entry = _bundle(
        tmp_path,
        facts=[
            {
                "accession": "0000000009-24-000009",
                "concept_qname": "us-gaap:AccountsPayableCurrent",
                "dimensions_json": "{}",
                "period_type": "instant",
            }
        ],
    )
    with pytest.raises(ValueError, match="disagrees"):
        build_filing_evidence(entry, _small_table(taxonomy))


def test_refuses_malformed_fact_qname(taxonomy: DomainTaxonomy, tmp_path: Path) -> None:
    """A fact qname with no prefix separator is a build refusal."""
    entry = _bundle(
        tmp_path,
        facts=[
            {
                "accession": _ACC,
                "concept_qname": "AccountsPayableCurrent",
                "dimensions_json": "{}",
                "period_type": "instant",
            }
        ],
    )
    with pytest.raises(ValueError, match="malformed"):
        build_filing_evidence(entry, _small_table(taxonomy))


def test_refuses_malformed_arc_endpoint(
    taxonomy: DomainTaxonomy, tmp_path: Path
) -> None:
    """An arc endpoint that is not a qname is a build refusal."""
    entry = _bundle(
        tmp_path,
        pres=[
            {
                "parent_qname": "not a qname",
                "child_qname": "us-gaap:AccountsPayableCurrent",
                "order": 1.0,
                "role_uri": _ROLE,
            }
        ],
    )
    with pytest.raises(ValueError, match="malformed"):
        build_filing_evidence(entry, _small_table(taxonomy))


def test_arc_only_concept_keeps_raw_blocks_with_silent_derivations(
    taxonomy: DomainTaxonomy, tmp_path: Path
) -> None:
    """A qname in arcs but not the table: raw blocks present, derived silent."""
    entry = _bundle(
        tmp_path,
        pres=[
            {
                "parent_qname": "ext:PlacedParent",
                "child_qname": "ext:PlacedChild",
                "order": 2.0,
                "role_uri": _ROLE,
            }
        ],
        calc=[
            {
                "parent_qname": "ext:PlacedParent",
                "child_qname": "ext:PlacedChild",
                "weight": 1.0,
                "order": 2.0,
                "role_uri": _ROLE,
            }
        ],
    )
    record = build_filing_evidence(entry, _small_table(taxonomy))
    child = record.entry("ext:PlacedChild")
    assert child is not None
    assert child.pres_parents == (("ext:PlacedParent", _ROLE, 2.0),)
    assert child.calc_parents == (("ext:PlacedParent", 1.0, _ROLE),)
    assert child.placed and not child.reported and not child.attested_placed
    assert child.calc_parent_heads == ()
    assert child.pres_horizon is None and child.calc_horizon is None
    assert child.placement_horizon is None and not child.placement_conflict
    assert len(record.bundle_fingerprint) == 64
    assert record.firm == "TST" and record.accession == _ACC
