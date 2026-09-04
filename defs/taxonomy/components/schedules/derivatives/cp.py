"""Commodity and energy derivative instruments (ASC 815)."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.engine import (
    build_derivative_grammar,
)
from defs.text.compounds import (
    expand_variants,
)

# Energy & Hydrocarbon underlyings
COMMODITY_ENERGY_UNDERLYINGS: tuple[str, ...] = (
    "commodity",
    "energy",
    "crude oil",
    "crude",
    "oil and gas",
    "natural gas",
    "natural gas liquids",
    "ngl",
    "diesel",
    "diesel fuel",
    "jet fuel",
    "heating oil",
    "bunker fuel",
    "bunker",
    "fuel oil",
    "gasoline",
    "propane",
    "butane",
    "ethane",
    "condensate",
    "coal",
    "electricity",
    "power",
    "refined products",
    "petroleum",
    "brent",
    "wti",
    "henry hub",
    "carbon credits",
    "emissions allowances",
    "recs",
)

# Agriculture, Grains, Softs & Livestock underlyings
COMMODITY_AGRI_UNDERLYINGS: tuple[str, ...] = (
    "agricultural",
    "corn",
    "wheat",
    "soybean",
    "soybeans",
    "soybean oil",
    "soybean meal",
    "grain",
    "grains",
    "sugar",
    "coffee",
    "cocoa",
    "cotton",
    "ethanol",
    "palm oil",
    "canola",
    "cattle",
    "live cattle",
    "feeder cattle",
    "hogs",
    "lean hogs",
    "lumber",
    "timber",
    "dairy",
    "milk",
)

# Metals (Industrial, Base & Precious) underlyings
COMMODITY_METALS_UNDERLYINGS: tuple[str, ...] = (
    "copper",
    "aluminum",
    "zinc",
    "nickel",
    "lead",
    "tin",
    "steel",
    "iron ore",
    "gold",
    "silver",
    "platinum",
    "palladium",
    "precious metals",
    "base metals",
    "industrial metals",
)

# Shipping & Freight underlyings
COMMODITY_FREIGHT_UNDERLYINGS: tuple[str, ...] = ("freight",)

COMMODITY_UNDERLYINGS: tuple[str, ...] = (
    *COMMODITY_ENERGY_UNDERLYINGS,
    *COMMODITY_AGRI_UNDERLYINGS,
    *COMMODITY_METALS_UNDERLYINGS,
    *COMMODITY_FREIGHT_UNDERLYINGS,
)

# Explicit financial derivative bases (rejects bare physical "supply", "purchase", "delivery", "order")
COMMODITY_DERIVATIVE_BASES: tuple[str, ...] = (
    "swap",
    "collar",
    "futures",
    "option",
    "call option",
    "put option",
    "call spread",
    "put spread",
    "swaption",
    "basis swap",
    "crack spread",
    "spark spread",
    "fixed-price swap",
    "derivative",
)

COMMODITY_DERIVATIVE_TERMS: tuple[str, ...] = build_derivative_grammar(
    underlyings=COMMODITY_UNDERLYINGS,
    bases=COMMODITY_DERIVATIVE_BASES,
)

# Physical Commercial Supply & NPNS Exclusions (ASC 815-10-15) owned by Commodity module
COMMODITY_PHYSICAL_SUPPLY_GUARDS: tuple[str, ...] = expand_variants(
    (
        "normal purchases and normal sales",
        "take-or-pay",
        "power purchase agreement",
        "natural gas delivery",
        "fuel supply agreement",
        "master supply agreement",
        "unconditional purchase obligation",
    )
)
