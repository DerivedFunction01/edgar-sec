"""Commodity contract-term primitives: unit lists, NPNS and
commercial-term vocabulary, per-class context terms, exchange
venues, and gazetteer pattern parts, as data. The taxonomy lives
in domain.commodities; determination stays with the consumers."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from edgar_sec.foundation.regex.builder import build_alternation


# Unit vocabulary: pre-port lists merged with old2's disjoint
# additions; old2 case variants (MMBtu, BTU, GJ, MWh) collapse onto
# the pre-port spellings. Strict = commodity measures, loose = general.
UNITS_STRICT = (
    "barrels",
    "bbl",
    "bbl/d",
    "btu",
    "gj",
    "mmbtu",
    "mmbtu/h",
    "mwh",
    "bushels",
    "cwt",
    "hundredweights",
    "pecks",
    "ounces",
    "pounds",
    "tons",
    "tonne",
    "long tons",
    "short tons",
    "joules",
    "gigajoules",
    "mcf",
    "mmcf",
    "bcf",
    "therm",
    "therms",
    "dth",
    "dekatherms",
    "barrels per day",
    "megawatt-hour",
    "metric tons",
)

UNITS_LOOSE = (
    "units",
    "items",
    "packages",
    "containers",
    "loads",
    "gallons",
    "gal",
    "liters",
    "ltr",
    "cubic meters",
    "m3",
    "cubic feet",
    "ft3",
    "hectoliters",
    "hL",
    "kiloliters",
    "kL",
    "megaliters",
    "ML",
    "gigaliters",
    "GL",
    "board foot",
    "bf",
    "sheets",
    "coils",
    "bundles",
    "pallets",
    "sacks",
    "bales",
    "heads",
    "carats",
    "ingots",
    "bars",
    "MT",
    "ST",
    "LT",
    "t",
    "lb",
    "oz",
    "bu",
    "L",
    "head",
)

UNITS: tuple[str, ...] = UNITS_STRICT + UNITS_LOOSE

# NPNS primitives: pre-port phrase patterns (regex source as data)
# and the plain-phrase set, which restores the physical-forward
# construction the derivatives-gate port dropped. Vocabulary only.
NPNS_PATTERNS = (
    r"normal\\s+purchases?\\s+(?:and|&)\\s+(?:normal\\s+)?sales?",
    "NPNS",
    r"own[- ]use\\s+exemption",
    r"physical\\s+(?:forward|delivery)\\s+(?:contracts?|agreements?)",
    r"physical\\s+settlements?",
)

NPNS_PHRASES = (
    "normal purchases and normal sales",
    "normal purchase and normal sale",
    "npns",
    "own-use exemption",
    "own use exemption",
    "physical forward contract",
    "physical forward contracts",
    "physical forward agreement",
    "physical forward agreements",
    "physical delivery contract",
    "physical delivery contracts",
    "physical delivery agreement",
    "physical delivery agreements",
    "physical delivery",
    "physical settlement",
)

# Physical/commercial primitives: pre-port term stems, the expanded
# literal set (the gate port dropped five of the eight families —
# orders, invoices, receipts, inventory, purchases), phrase patterns.
PHYSICAL_COMMERCIAL_TERM_PATTERNS = (
    "deliver(?:y|ies)",
    "orders?",
    "suppl(?:y|ies)",
    "invoices?",
    "shipments?",
    "receipts?",
    "inventor(?:y|ies)",
    "purchases?",
)

COMMERCIAL_TERMS = (
    "delivery",
    "deliveries",
    "order",
    "orders",
    "supply",
    "supplies",
    "invoice",
    "invoices",
    "shipment",
    "shipments",
    "receipt",
    "receipts",
    "inventory",
    "inventories",
    "purchase",
    "purchases",
)

COMMERCIAL_PHRASE_PATTERNS = (
    "take[- ]or[- ]pay",
    r"purchase\\s+orders?",
    r"master\\s+supply",
    build_alternation(
        [
            "off[- ]take",
            r"unconditional\\s+purchases?",
            "requirements?",
            "procurement",
            "throughput",
            "capacity",
            "delivery",
            "storage",
            "supply",
            "sales",
        ]
    )
    + "[- ]"
    + build_alternation(
        [
            "arrangements?",
            "instruments?",
            "commitments?",
            "obligations?",
            "agreements?",
            "contracts?",
        ]
    ),
    "(?:inventor(?:y|ies)|deliver(?:y|ies)|suppl(?:y|ies)|shipments?|purchases?|invoices?|receipts?|orders?)[- ]forwards?",
)

# Per-class context terms (pre-port standing). The gap for
# chemicals and construction is carried as-is (D6): those classes
# have no entry here.
CONTEXT_TERMS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "crops": (
            "crops?",
            "harvest(?:s|ing)?",
            "yields?",
            "acreage",
            "plant(?:ing|ed)",
            "bushels?",
            "grains?",
        ),
        "energy": (
            "PJM",
            "ERCOT",
            "MISO",
            "SPP",
            "CAISO",
            "NYISO",
            "ISO-NE",
            "Henry Hub",
            "WTI",
            "West Texas Intermediate",
            "Cushing",
            "Mont Belvieu",
            "TTF",
            "JKM",
            "Dominion South",
            "Platts",
            "Argus",
            "OPIS",
            "Brent",
            "baseload",
            "peak load",
            "off-peak",
            "on-peak",
            "capacity",
            "power " + build_alternation(["assets", "generation", "supply"]),
            "fuel",
            "energy",
            build_alternation(["dark", "crack", "spark"]) + " spreads?",
        ),
        "environmental": (
            "greenhouse",
            "carbon",
        ),
        "forestry": (
            "logging",
            "mills?",
            "pulp",
            "paper",
        ),
        "livestock": (
            "livestock",
            "feed",
            "herd",
            "breeding",
            "heads?",
        ),
        "metals": (
            "mining",
            "mines?",
            "ores?",
            "smelt(?:ing|er)?",
            "refin" + build_alternation(["ing", "ery", "ed"]),
            "bullion",
        ),
        "seafood": (
            "catch",
            "aquaculture",
            "fishery",
            "fisheries",
        ),
    }
)

# Derivative-exchange venue patterns (pre-port shared_context
# standing, regex source as data).
EXCHANGE_VENUE_PATTERNS = (
    build_alternation(
        [
            "BIFFEX",
            "NYMEX",
            "COMEX",
            "NYBOT",
            "LIFFE",
            "TOCOM",
            "Eurex",
            "CBOT",
            "CBOE",
            "KCBT",
            "MGEX",
            "BM&F",
            "CME",
            "ICE",
            "LME",
            "DME",
            "MX",
        ]
    ),
    build_alternation(
        [
            r"London\\s+International\\s+Financial\\s+Futures\\s+and\\s+Options",
            r"Chicago\\s+Board\\s+Options",
            r"New\\s+York\\s+Mercantile",
            r"Chicago\\s+Mercantile",
            r"Minneapolis\\s+Grain",
            r"Dubai\\s+Mercantile",
            r"Tokyo\\s+Commodity",
            "Intercontinental",
            r"London\\s+Metal",
            "Montreal",
            "Baltic",
        ]
    )
    + r"\\s+Exchange",
    build_alternation([r"Kansas\\s+City", r"New\\s+York", "Chicago"])
    + r"\\s+Board\\s+of\\s+Trade",
    r"ICE\\s+Futures",
    r"[Dd]erivative\\s+[Mm]arkets?",
    r"Commodity\\s+Exchange(?!\\s+Act)",
)

# The two dynamic gazetteer builders of the pre-port map are not
# ported as code; their component lists are carried as pattern parts.
ENERGY_PATTERN_PARTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "prefixes": ("bio", "liquefied", "liquid"),
        "modifiers": (
            "bunker",
            "marine",
            "jet",
            "(?:air|aero)plane",
            "helicopter",
            "plane",
            "aero",
            "aviation",
            "crude",
            "heating",
            "coking",
            "natural",
            "carbon",
            "renewable",
            "liquid",
        ),
        "bases": (
            "fuels?",
            "oils?",
            "energy",
            "coal",
            "gas(?:oline)?",
            "propane",
            "petroleum",
            "diesel",
            "butane",
            "electricity",
            "distillates",
            "ethane",
            "ethanol",
            "kerosene",
            "LNG",
            "LPG",
            "solar",
            "wind",
        ),
    }
)

METALS_PATTERN_PARTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "prefixes": ("precious", "rare earth", "base", "scrap", "silicon"),
        "modifiers": (
            "stainless",
            "refined",
            "raw",
            "unrefined",
            "high[- ]grade",
            "low[- ]grade",
        ),
        "bases": (
            "aluminum",
            "copper",
            "iron",
            "gold",
            "silver",
            "metals?",
            "ores?",
            "(?:stainless[- ])?steel",
            "titanium",
            "uranium",
            "nickel",
            "zinc",
            "lead",
            "tin",
            "platinum",
            "palladium",
            "rhodium",
            "cobalt",
            "molybdenum",
            "chromium",
            "lithium",
            "magnesium",
            "vanadium",
            "alumina",
            "bauxite",
            "antimony",
            "arsenic",
            "bismuth",
            "indium",
            "gallium",
            "graphite",
            "potassium",
            "diamonds?",
            "gemstones?",
        ),
    }
)

COMMODITY_HEADER_PHRASE = "commodity contracts"  # the gate's header

__all__ = [
    "COMMERCIAL_PHRASE_PATTERNS",
    "COMMERCIAL_TERMS",
    "COMMODITY_HEADER_PHRASE",
    "CONTEXT_TERMS",
    "ENERGY_PATTERN_PARTS",
    "EXCHANGE_VENUE_PATTERNS",
    "METALS_PATTERN_PARTS",
    "NPNS_PATTERNS",
    "NPNS_PHRASES",
    "PHYSICAL_COMMERCIAL_TERM_PATTERNS",
    "UNITS",
    "UNITS_LOOSE",
    "UNITS_STRICT",
]
