"""Corpus loading and battery data for the XBRL census runner."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer

REPO = Path(__file__).resolve().parents[2]
XBRL_FIXTURES = REPO / "tests" / "fixtures" / "xbrl"
CORPUS_NAMES = ("seed", "vintage")


def bundle_dir(folder: str) -> Path:
    """A corpus bundle folder; it must exist in exactly one corpus root."""
    hits = [
        XBRL_FIXTURES / name / folder
        for name in CORPUS_NAMES
        if (XBRL_FIXTURES / name / folder).is_dir()
    ]
    if len(hits) != 1:
        raise ValueError(f"bundle folder {folder} in {len(hits)} corpus roots")
    return hits[0]


def corpus_cohort_rows() -> list[dict]:
    """All canonical cohort registry rows, seed first, then vintage."""
    rows: list[dict] = []
    for name in ("seed_cohort.json", "vintage_cohort.json"):
        rows.extend(json.loads((XBRL_FIXTURES / name).read_text(encoding="utf-8")))
    return rows


def corpus_source_bundles() -> list[dict]:
    """All fixture source registry rows, seed corpus first, then vintage."""
    bundles: list[dict] = []
    for name in CORPUS_NAMES:
        payload = json.loads(
            (XBRL_FIXTURES / name / "fixture_source_registry.json").read_text(
                encoding="utf-8"
            )
        )
        bundles.extend(payload["bundles"])
    return bundles


CASH_Q = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
ASSETS_Q = "us-gaap:Assets"
XVA_Q = "bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets"

PROBE_FIRMS = ["msft", "aapl", "bac", "jpm", "xom", "gis", "pld"]
PROBE_TERMS = {
    "loose": ["revenue"],
    "derivatives": [
        "Derivative Assets",
        "Derivative Liabilities",
        "us-gaap:DerivativeAssets",
        "us-gaap:DerivativeLiabilities",
        "Notional",
    ],
    "simple": [
        CASH_Q,
        ASSETS_Q,
        "us-gaap:Liabilities",
        "us-gaap:StockholdersEquity",
        "us-gaap:NetIncomeLoss",
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    ],
}
SPAN_FY = {
    "msft": 2024,
    "aapl": 2024,
    "bac": 2024,
    "jpm": 2024,
    "xom": 2024,
    "gis": 2024,
    "pld": 2024,
    "wmt": 2024,
    "nvda": 2024,
    "de": 2024,
    "tsn": 2024,
    "pep": 2024,
    "jnj": 2024,
    "amzn": 2023,
}
SPAN_FIRMS = list(SPAN_FY)
SPAN_RO = [
    "revenue",
    "Net Income",
    "cfo",
    CASH_Q,
    ASSETS_Q,
    "us-gaap:EarningsPerShareDiluted",
    "eps",
]
SPAN_VERIFY = ["revenue", "Net Income", "cfo", CASH_Q, ASSETS_Q]
PINNED_CLASS_V = {
    "gis": ["us-gaap:GrossProfit"],
    "bac": ["us-gaap:CommonStockDividendsPerShareDeclared"],
    "amzn": ["us-gaap:PaymentsToAcquireAvailableForSaleSecuritiesDebt"],
    "nvda": [
        "nvda:EquitySecuritiesWithoutReadilyDeterminableFairValueNetUpward"
        "DownwardPriceAdjustmentAndImpairmentLossAnnualAmount"
    ],
    "jnj": [
        "us-gaap:ProceedsFromIssuanceOfCommercialPaper",
        "jnj:DebtForEquityExchangeLossOnSharesExchanged",
    ],
    "jpm": ["us-gaap:PaymentsToAcquireBusinessesGross"],
}
EXTRA_TERMS = ["Net Income", "cfo", "eps", "us-gaap:EarningsPerShareDiluted"]
PROBE_TERMS_FLAT = [t for terms in PROBE_TERMS.values() for t in terms]


def span_days(start: str | None, end: str | None) -> int | None:
    """Calendar days between two ISO dates, or None when either is absent."""
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def load_seed_facts(folder: str) -> tuple[XbrlFact, ...]:
    """Load one corpus bundle's facts from its committed parquet."""
    rows = pq.read_table(bundle_dir(folder) / "facts.parquet").to_pylist()
    return tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=row["numeric_value"]
            if row["numeric_value"] is not None
            else row["text_value"],
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in rows
    )


def load_seed_arcs(folder: str) -> tuple[CalculationArc, ...]:
    """Load one corpus bundle's calculation arcs from its committed parquet."""
    rows = pq.read_table(bundle_dir(folder) / "calculation_arcs.parquet").to_pylist()
    return tuple(
        CalculationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            weight=row["weight"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in rows
    )


def load_seed_declarations(folder: str):
    """Load one corpus bundle's persisted concept declarations."""
    from edgar_sec.engine.xbrl.storage.storage import (
        declarations_from_arrow_table,
        read_declarations_parquet,
    )

    path = bundle_dir(folder) / "declarations.parquet"
    return declarations_from_arrow_table(read_declarations_parquet(path))


def make_facade(firm: str, taxonomy) -> Xbrl:
    """Build the client facade over one firm's corpus bundle, declarations in."""
    registry = corpus_source_bundles()
    folder = next(
        item["folder"] for item in registry if item["firm"].lower() == firm.lower()
    )
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(
            calculation_arcs=load_seed_arcs(folder),
            declarations=load_seed_declarations(folder),
        ),
    )
    return Xbrl(bundle, taxonomy)


def make_facade_folder(folder: str, taxonomy) -> Xbrl:
    """Build the facade over a seed folder without bundle declarations."""
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(calculation_arcs=load_seed_arcs(folder)),
    )
    return Xbrl(bundle, taxonomy)


def corpus_folders() -> list[str]:
    """All grounded corpus fixture folders, in filename order."""
    return sorted(
        p.name
        for name in CORPUS_NAMES
        for p in (XBRL_FIXTURES / name).iterdir()
        if p.is_dir()
    )


def firm_fiscal_year(facts: tuple[XbrlFact, ...]) -> int:
    """The fiscal year of a filing: end year of its most-carried duration period."""
    counts: Counter = Counter()
    for f in facts:
        if (
            not f.dimensions
            and f.period_type == "duration"
            and f.start_date
            and f.end_date
        ):
            counts[(f.start_date, f.end_date)] += 1
    (start, end), _ = counts.most_common(1)[0]
    return int(end[:4])


def annual_period(facts: tuple[XbrlFact, ...], fiscal_year: int) -> tuple[str, str]:
    """The longest undimensioned duration period ending in the fiscal year."""
    counts: Counter = Counter()
    for f in facts:
        if (
            not f.dimensions
            and f.period_type == "duration"
            and f.start_date
            and f.end_date
            and f.end_date[:4] == str(fiscal_year)
        ):
            counts[(f.start_date, f.end_date)] += 1
    return max(counts, key=lambda p: (span_days(*p) or 0, counts[p]))


def headline_revenue_qname(
    facts: tuple[XbrlFact, ...],
    tokenizer: ConceptTokenizer,
    fiscal_year: int,
    atom_cache: dict,
) -> str | None:
    """The firm's largest bare/ASC-606 revenue qname at the annual period."""
    start, end = annual_period(facts, fiscal_year)
    best: tuple[float, str] | None = None
    for f in facts:
        if f.dimensions or f.period_type != "duration":
            continue
        if (f.start_date, f.end_date) != (start, end):
            continue
        if not isinstance(f.value, (int, float)):
            continue
        q = f.concept_qname
        if q not in atom_cache:
            atom = tokenizer.tokenize(q).atom
            atom_cache[q] = (atom.head, atom.modifiers)
        head, mods = atom_cache[q]
        archetype = mods in (
            frozenset(),
            frozenset({"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"}),
        )
        if head == "H_REVENUE" and archetype:
            if best is None or float(f.value) > best[0]:
                best = (float(f.value), q)
    return best[1] if best else None


def discovered_concepts(facts: tuple[XbrlFact, ...], fiscal_year: int) -> list[str]:
    """Supplement battery: numeric concepts carried only at sub-annual spans."""
    seen: dict[str, None] = {}
    fy_spans: dict[str, list[int]] = {}
    numeric_fy: set[str] = set()
    long_anywhere: set[str] = set()
    for f in facts:
        if f.dimensions or f.period_type != "duration" or not f.start_date:
            continue
        span = span_days(f.start_date, f.end_date)
        if span is None:
            continue
        if span >= 300:
            long_anywhere.add(f.concept_qname)
        if f.end_date and f.end_date[:4] == str(fiscal_year):
            fy_spans.setdefault(f.concept_qname, []).append(span)
            seen.setdefault(f.concept_qname)
            if isinstance(f.value, (int, float)):
                numeric_fy.add(f.concept_qname)
    out = []
    for q in seen:
        if q in long_anywhere or q not in numeric_fy:
            continue
        if fy_spans.get(q) and all(s < 300 for s in fy_spans[q]):
            out.append(q)
        if len(out) == 2:
            break
    return out


def textblock_qnames(facts: tuple[XbrlFact, ...]) -> set[str]:
    """Qnames carrying no numeric fact anywhere in the filing."""
    numeric: set[str] = set()
    all_q: set[str] = set()
    for f in facts:
        all_q.add(f.concept_qname)
        if isinstance(f.value, (int, float)):
            numeric.add(f.concept_qname)
    return all_q - numeric


def corpus_cohort_entries() -> tuple:
    """Cohort entries over the grounded corpus bundles, accessions authoritative."""
    from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry

    registry = corpus_cohort_rows()
    sources = corpus_source_bundles()
    folder_by_accession = {s["cohort_accession"]: s["folder"] for s in sources}
    entries = []
    for item in registry:
        folder = folder_by_accession.get(item["accession"])
        if folder is None:
            raise ValueError(f"seed bundle for accession {item['accession']}")
        facts_path = bundle_dir(folder) / "facts.parquet"
        accessions = set(
            pq.read_table(facts_path, columns=["accession"]).column(0).to_pylist()
        )
        if len(accessions) != 1:
            raise ValueError(f"seed bundle for {item['firm']}: {accessions}")
        entries.append(
            CohortEntry(
                accession=accessions.pop(),
                facts_path=facts_path,
                firm=item["firm"],
            )
        )
    return tuple(entries)


def latest_undimensioned_fact(folder: str, qname: str) -> XbrlFact:
    """The latest-instant undimensioned fact for a qname in one corpus bundle."""
    own = [
        fact
        for fact in load_seed_facts(folder)
        if fact.concept_qname == qname and not fact.dimensions
    ]
    return max(own, key=lambda fact: fact.instant_date or "")
