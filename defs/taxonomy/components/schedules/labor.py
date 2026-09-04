"""Labor, collective bargaining agreements, and union representation schedules."""

from __future__ import annotations

from enum import Enum

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack
from defs.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)

# =============================================================================
# INDUSTRY & OCCUPATION VOCABULARY TIERS
# =============================================================================


class IndustryGroup(Enum):
    HEAVY = "heavy"
    MANUFACTURING = "manufacturing"
    TRANSPORT = "transport"
    SERVICE = "service"
    NATURAL = "natural"


class OccupationGroup(Enum):
    AVIATION = "aviation"
    TRANSPORT = "transport"
    TRADES = "trades"
    PUBLIC_SAFETY = "public_safety"
    HEALTHCARE = "healthcare"
    HOSPITALITY = "hospitality"
    MEDIA = "media"
    OTHER = "other"


INDUSTRY_PREFIX_TERMS: dict[IndustryGroup, tuple[str, ...]] = {
    IndustryGroup.HEAVY: (
        "steel",
        "aluminum",
        "iron",
        "metal",
        "coal",
        "mining",
        "oil",
        "gas",
        "energy",
        "chemical",
        "asbestos",
        "rubber",
        "glass",
        "meatpacking",
    ),
    IndustryGroup.MANUFACTURING: (
        "automotive",
        "auto",
        "shipbuilding",
        "electronics",
        "electrical",
        "manufacturing",
        "industrial",
        "packaging",
        "textile",
        "pulp",
        "paper",
        "mill",
        "plant",
        "brick",
    ),
    IndustryGroup.TRANSPORT: (
        "aviation",
        "rail",
        "railroad",
        "transit",
        "trucking",
        "transport",
        "transportation",
        "maritime",
        "longshore",
        "dock",
        "port",
        "warehouse",
        "postal",
        "airline",
        "airport",
        "flight",
    ),
    IndustryGroup.SERVICE: (
        "retail",
        "food",
        "hospitality",
        "hotel",
        "healthcare",
        "pharmaceutical",
        "telecommunications",
        "communication",
    ),
    IndustryGroup.NATURAL: (
        "agriculture",
        "agricultural",
        "farm",
        "forestry",
        "timber",
        "building",
        "construction",
    ),
}

OCCUPATION_GROUP_TERMS: dict[OccupationGroup, tuple[str, ...]] = {
    OccupationGroup.AVIATION: expand_variants(
        (
            "pilot",
            "flight attendant",
            "flight crew",
            "air traffic operator",
            "airline attendant",
            "air traffic controller",
        )
    ),
    OccupationGroup.TRANSPORT: expand_variants(
        (
            "driver",
            "truck driver",
            "delivery driver",
            "conductor",
            "operator",
            "locomotive engineer",
        )
    ),
    OccupationGroup.TRADES: expand_variants(
        (
            "electrician",
            "carpenter",
            "plumber",
            "welder",
            "pipefitter",
            "boilermaker",
            "millwright",
            "fabricator",
            "assembler",
            "dispatcher",
            "mechanic",
            "machinist",
            "longshoreman",
            "bricklayer",
            "teamster",
        )
    ),
    OccupationGroup.PUBLIC_SAFETY: expand_variants(
        (
            "police",
            "sheriff",
            "security guard",
            "firefighter",
            "security officer",
        )
    ),
    OccupationGroup.HEALTHCARE: expand_variants(
        ("nurse", "doctor", "surgeon", "physician")
    ),
    OccupationGroup.HOSPITALITY: expand_variants(
        ("chef", "cook", "waiter", "bartender", "cashier")
    ),
    OccupationGroup.MEDIA: expand_variants(
        ("actor", "writer", "director", "producer", "composer", "filmmaker")
    ),
    OccupationGroup.OTHER: expand_variants(
        ("technician", "custodian", "janitor", "miner", "scientist")
    ),
}

# =============================================================================
# DYNAMIC LABOR COMPOUND BUILDER
# =============================================================================

_COLLECTIVE = ("collective", "labor", "labour", "union", "trade union")
_BARGAIN = expand_variants(("bargaining", "negotiation", "negotiating"))
_CONTRACT_NOUNS = expand_variants(
    (
        "agreement",
        "contract",
        "settlement",
        "accord",
        "unit",
        "organization",
        "relation",
    )
)
_WORKER_GENERIC = expand_variants(
    ("worker", "employee", "laborer", "personnel", "workforce", "staff")
)

_REPRESENTATION_PREFIXES = (
    "represented by",
    "covered by",
    "subject to",
    "affiliated with",
)
_REPRESENTATION_TARGETS = (
    "union",
    "unions",
    "labor union",
    "trade union",
    "collective bargaining agreement",
    "collective agreement",
    "works council",
)

_LABOR_METRIC_PREFIXES = (
    "number of",
    "percent of",
    "percentage of",
    "total",
)
_LABOR_METRIC_TARGETS = (
    "employees represented",
    "workers represented",
    "union employees",
    "represented employees",
    "bargaining unit employees",
    "union members",
)

_UNION_ACRONYMS = (
    "uaw",
    "afl-cio",
    "alpa",
    "twu",
    "cwa",
    "seiu",
    "ibew",
    "ibt",
    "iam",
    "ufcw",
    "usw",
    "umwa",
    "ilwu",
    "afscme",
    "liuna",
    "bctgm",
    "iatse",
    "wga",
    "sag-aftra",
    "ifpte",
    "bmwed",
    "smwia",
    "iuoe",
    "apfa",
    "unite here",
)

_SCHEDULE_HEADERS = (
    "status of agreement",
    "contract amendable",
    "contract amendable date",
    "amendable date",
    "expiration date",
    "amendment date",
    "works council",
    "works councils",
    "co-determination",
    "codetermination",
)

# Flattened industry worker compounds (e.g., "steel workers", "mining workforce")
_INDUSTRY_WORKER_TERMS = expand_compounds(
    [t for terms in INDUSTRY_PREFIX_TERMS.values() for t in terms],
    _WORKER_GENERIC,
)

# Flattened occupation list
_ALL_OCCUPATION_TERMS = expand_alternations(
    [terms for terms in OCCUPATION_GROUP_TERMS.values()]
)

# Dynamic union organization compounds (e.g. "association of flight attendants", "united steelworkers")
_UNION_NOUN_ORGS = (
    "association",
    "brotherhood",
    "federation",
    "guild",
    "society",
    "order",
    "alliance",
)
_UNION_ADJ_ORGS = ("amalgamated", "united", "international", "national")
_ALL_UNION_ORGS = expand_alternations(_UNION_NOUN_ORGS, _UNION_ADJ_ORGS, "union")
_WORKER_TARGETS = expand_alternations(_ALL_OCCUPATION_TERMS, _INDUSTRY_WORKER_TERMS)

DYNAMIC_UNION_NAMES: tuple[str, ...] = expand_alternations(
    expand_compounds(_UNION_NOUN_ORGS, "of", _WORKER_TARGETS),
    expand_compounds(_UNION_ADJ_ORGS, _WORKER_TARGETS),
    expand_compounds(_WORKER_TARGETS, _ALL_UNION_ORGS),
    expand_compounds([u for u in _ALL_UNION_ORGS if u != "union"], "union"),
)

# Primary Tier: Distinctive collective bargaining, representation, and union schedule indicators
LABOR_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    expand_compounds(_COLLECTIVE, _BARGAIN, (None, _CONTRACT_NOUNS)),
    expand_compounds(("labor", "labour", "trade union", "union"), _CONTRACT_NOUNS),
    expand_compounds(_REPRESENTATION_PREFIXES, (None, "a"), _REPRESENTATION_TARGETS),
    expand_compounds(_LABOR_METRIC_PREFIXES, (None, "covered"), _LABOR_METRIC_TARGETS),
    _SCHEDULE_HEADERS,
)

# Supporting Tier: Acronyms, occupation stubs, industry worker groups, employee groupings, and dynamic union names
LABOR_SUPPORTING_TERMS: tuple[str, ...] = expand_alternations(
    expand_variants(("employee group", "bargaining group")),
    _UNION_ACRONYMS,
    _INDUSTRY_WORKER_TERMS,
    _ALL_OCCUPATION_TERMS,
    DYNAMIC_UNION_NAMES,
)

LABOR_VETOES: tuple[str, ...] = ("activities",)

_LABOR_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="labor_contracts",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "labor_primary",
                    LABOR_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "labor_support",
                    LABOR_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=LABOR_VETOES,
    )
)

LABOR_CONTRACTS_SPEC = TableFamilySpec(
    name="labor_contracts",
    shape=ShapeConstraint(
        min_rows=3, max_rows=50, min_cols=2, min_numeric_density=0.08
    ),
    evidence_pack=_LABOR_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=50,
)

__all__ = [
    "DYNAMIC_UNION_NAMES",
    "LABOR_CONTRACTS_SPEC",
    "LABOR_PRIMARY_TERMS",
    "LABOR_SUPPORTING_TERMS",
    "LABOR_VETOES",
    "IndustryGroup",
    "OccupationGroup",
]
