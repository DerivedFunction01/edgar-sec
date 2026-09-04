"""Common measurement units for numeric cell recognition in financial tables."""

from __future__ import annotations

from typing import Any

MEASUREMENT_UNITS: dict[str, dict[str, Any]] = {
    # SI / metric mass
    "MILLIGRAM": {"names": ["milligram", "milligrams"], "symbols": ["mg"]},
    "GRAM": {"names": ["gram", "grams"], "symbols": ["g"]},
    "KILOGRAM": {"names": ["kilogram", "kilograms"], "symbols": ["kg"]},
    "TONNE": {
        "names": ["tonne", "tonnes", "metric ton", "metric tons"],
        "symbols": ["t", "MT", "Mt"],
    },
    # US / imperial mass
    "OUNCE": {"names": ["ounce", "ounces"], "symbols": ["oz"]},
    "POUND": {"names": ["pound", "pounds"], "symbols": ["lb", "lbs"]},
    "TON": {
        "names": ["ton", "tons", "short ton", "short tons"],
        "symbols": ["ton", "tons"],
    },
    # SI / metric volume
    "MILLILITER": {
        "names": ["milliliter", "milliliters", "millilitre", "millilitres"],
        "symbols": ["mL", "ml"],
    },
    "LITER": {"names": ["liter", "liters", "litre", "litres"], "symbols": ["L", "l"]},
    "CUBIC_METER": {
        "names": ["cubic meter", "cubic meters", "cubic metre", "cubic metres"],
        "symbols": ["m³", "m3", "cbm"],
    },
    # US / imperial volume
    "FLUID_OUNCE": {"names": ["fluid ounce", "fluid ounces"], "symbols": ["fl oz"]},
    "GALLON": {"names": ["gallon", "gallons"], "symbols": ["gal"]},
    "BARREL": {"names": ["barrel", "barrels"], "symbols": ["bbl", "bbls", "BBL"]},
    "CUBIC_FOOT": {
        "names": ["cubic foot", "cubic feet"],
        "symbols": ["ft³", "ft3", "cf"],
    },
    "THOUSAND_CUBIC_FOOT": {
        "names": ["thousand cubic feet"],
        "symbols": ["Mcf", "MCF"],
    },
    "MILLION_CUBIC_FOOT": {"names": ["million cubic feet"], "symbols": ["MMcf"]},
    # Energy
    "JOULE": {"names": ["joule", "joules"], "symbols": ["J"]},
    "KILOJOULE": {"names": ["kilojoule", "kilojoules"], "symbols": ["kJ"]},
    "MEGAJOULE": {"names": ["megajoule", "megajoules"], "symbols": ["MJ"]},
    "GIGAJOULE": {"names": ["gigajoule", "gigajoules"], "symbols": ["GJ"]},
    "WATT_HOUR": {"names": ["watt hour", "watt hours"], "symbols": ["Wh"]},
    "KILOWATT_HOUR": {"names": ["kilowatt hour", "kilowatt hours"], "symbols": ["kWh"]},
    "MEGAWATT_HOUR": {"names": ["megawatt hour", "megawatt hours"], "symbols": ["MWh"]},
    "MEGAWATT": {"names": ["megawatt", "megawatts"], "symbols": ["MW"]},
    "GIGAWATT": {"names": ["gigawatt", "gigawatts"], "symbols": ["GW"]},
    "TERAWATT": {"names": ["terawatt", "terawatts"], "symbols": ["TW"]},
    "KILOWATT": {"names": ["kilowatt", "kilowatts"], "symbols": ["kW"]},
    "GIGAWATT_HOUR": {"names": ["gigawatt hour", "gigawatt hours"], "symbols": ["GWh"]},
    "TERAWATT_HOUR": {"names": ["terawatt hour", "terawatt hours"], "symbols": ["TWh"]},
    "BTU": {
        "names": ["british thermal unit", "british thermal units"],
        "symbols": ["BTU", "btu"],
    },
    "MILLION_BTU": {
        "names": ["million british thermal units"],
        "symbols": ["MMBtu", "MMBTU"],
    },
    # Length / distance
    "MILLIMETER": {
        "names": ["millimeter", "millimeters", "millimetre", "millimetres"],
        "symbols": ["mm"],
    },
    "CENTIMETER": {
        "names": ["centimeter", "centimeters", "centimetre", "centimetres"],
        "symbols": ["cm"],
    },
    "METER": {"names": ["meter", "meters", "metre", "metres"], "symbols": ["m"]},
    "KILOMETER": {
        "names": ["kilometer", "kilometers", "kilometre", "kilometres"],
        "symbols": ["km"],
    },
    "INCH": {"names": ["inch", "inches"], "symbols": ["in"]},
    "FOOT": {"names": ["foot", "feet"], "symbols": ["ft"]},
    "YARD": {"names": ["yard", "yards"], "symbols": ["yd"]},
    "MILE": {"names": ["mile", "miles"], "symbols": ["mi"]},
    # Area
    "SQUARE_METER": {
        "names": ["square meter", "square meters", "square metre", "square metres"],
        "symbols": ["m²", "m2"],
    },
    "SQUARE_FOOT": {"names": ["square foot", "square feet"], "symbols": ["ft²", "ft2"]},
    "HECTARE": {"names": ["hectare", "hectares"], "symbols": ["ha"]},
    "ACRE": {"names": ["acre", "acres"], "symbols": ["ac"]},
    # Pressure / other
    "PASCAL": {"names": ["pascal", "pascals"], "symbols": ["Pa"]},
    "KILOPASCAL": {"names": ["kilopascal", "kilopascals"], "symbols": ["kPa"]},
    "BAR": {"names": ["bar", "bars"], "symbols": ["bar"]},
    "PSI": {"names": ["pounds per square inch"], "symbols": ["psi"]},
    # Count / quantity
    "UNIT": {"names": ["unit", "units"], "symbols": ["units"]},
    "THOUSAND": {"names": ["thousand"], "symbols": ["K"]},
    "MILLION": {"names": ["million"], "symbols": ["MM", "M"]},
    "BILLION": {"names": ["billion"], "symbols": ["B"]},
    # Time / duration
    "YEAR": {"names": ["year", "years"], "symbols": ["year", "years", "yr", "yrs"]},
    "MONTH": {
        "names": ["month", "months"],
        "symbols": ["month", "months", "mo", "mos"],
    },
    "DAY": {"names": ["day", "days"], "symbols": ["day", "days"]},
}

UNIT_SYMBOLS: set[str] = set()
for _data in MEASUREMENT_UNITS.values():
    UNIT_SYMBOLS.update(_data.get("symbols", []))

__all__ = [
    "MEASUREMENT_UNITS",
    "UNIT_SYMBOLS",
]
