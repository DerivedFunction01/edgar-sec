"""Taxonomy record families: geography, industries, axes, units, frames, roles."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.schema.atoms import Atom


def read_records(source: Path) -> list[dict[str, Any]]:
    """Read a list of record mappings from a JSON, CSV, or TSV file."""
    if source.suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"expected list of records in {source}")
        return [dict(item) for item in payload]
    delimiter = "\t" if source.suffix == ".tsv" else ","
    with source.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        return [dict(row) for row in reader]


@dataclass(frozen=True, slots=True)
class GeoHierarchyEdge:
    """Geography hierarchy meronymy edge."""

    child_geo_node: str
    parent_geo_node: str
    decomposition_scheme: str = "PART_WHOLE"
    relation_type: str = "MERONYM"
    notes: str = ""

    @property
    def child_qname(self) -> str:
        return self.child_geo_node

    @property
    def parent_qname(self) -> str:
        return self.parent_geo_node

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeoHierarchyEdge:
        """Create a GeoHierarchyEdge from raw dictionary mapping."""
        return cls(
            child_geo_node=str(data["child_geo_node"]),
            parent_geo_node=str(data["parent_geo_node"]),
            decomposition_scheme=str(data.get("decomposition_scheme", "PART_WHOLE")),
            relation_type=str(data.get("relation_type", "MERONYM")),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True, slots=True)
class GeoResolution:
    """Resolved geographic coordinate with domicile-relative domestic/foreign status."""

    canonical_node: str
    is_domestic: bool
    is_foreign: bool
    ancestor_regions: tuple[str, ...]
    decomposition_schemes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndustryProfile:
    """Firm entity industry and classification profile."""

    firm_id: str
    company_name: str
    cik: str
    sic_code: int
    ff48_industry: str
    sector: str
    domicile: str
    functional_currency: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndustryProfile:
        """Create an IndustryProfile from raw dictionary mapping."""
        return cls(
            firm_id=str(data["firm_id"]),
            company_name=str(data["company_name"]),
            cik=str(data["cik"]),
            sic_code=int(data["sic_code"]),
            ff48_industry=str(data["ff48_industry"]),
            sector=str(data["sector"]),
            domicile=str(data.get("domicile", "US")),
            functional_currency=str(data.get("functional_currency", "USD")),
        )


@dataclass(frozen=True, slots=True)
class AxisFamilyMapping:
    """Mapping of axis pattern to canonical axis family and scope tokens."""

    axis_pattern: str
    axis_family: str
    description: str = ""
    default_axis_qname: str = ""
    scope_tokens: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AxisFamilyMapping:
        """Create an AxisFamilyMapping from raw dictionary mapping."""
        return cls(
            axis_pattern=str(data["axis_pattern"]),
            axis_family=str(data["axis_family"]),
            description=str(data.get("description", "")),
            default_axis_qname=str(data.get("default_axis_qname", "")),
            scope_tokens=tuple(str(t).lower() for t in data.get("scope_tokens", ())),
        )


@dataclass(frozen=True, slots=True)
class UnitMapping:
    """Mapping of raw XBRL unit token to canonical unit class."""

    raw_unit: str
    unit_class: str
    currency_code: str | None = None
    unit_type: str = "CURRENCY"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitMapping:
        """Create a UnitMapping from raw dictionary mapping."""
        return cls(
            raw_unit=str(data["raw_unit"]),
            unit_class=str(data["unit_class"]),
            currency_code=str(data["currency_code"])
            if data.get("currency_code")
            else None,
            unit_type=str(data.get("unit_type", "CURRENCY")),
        )


@dataclass(frozen=True, slots=True)
class GrammaticalFrame:
    """Declarative grammatical frame for directional and polarity normalization."""

    frame_id: str
    prefix_tokens: tuple[str, ...]
    direction: float = 1.0
    polarity: str = "NEUTRAL"
    strip_tokens: tuple[str, ...] = ()
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GrammaticalFrame:
        """Create a GrammaticalFrame from raw dictionary mapping."""
        raw_prefix = data.get("prefix_tokens", ())
        raw_strip = data.get("strip_tokens", ())
        return cls(
            frame_id=str(data["frame_id"]),
            prefix_tokens=tuple(str(t).lower() for t in raw_prefix),
            direction=float(data.get("direction", 1.0)),
            polarity=str(data.get("polarity", "NEUTRAL")),
            strip_tokens=tuple(str(t).lower() for t in raw_strip),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class MemberRoleMapping:
    """Mapping of member substring pattern to semantic role."""

    pattern: str
    role: str
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemberRoleMapping:
        """Create a MemberRoleMapping from raw dictionary mapping."""
        return cls(
            pattern=str(data["pattern"]).lower(),
            role=str(data["role"]),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class InstrumentEdge:
    """Financial instrument hyponymy edge."""

    child_instrument: str
    parent_instrument: str
    relation_type: str = "SUBTYPE_OF"
    description: str = ""
    underlying_risk: str = "ALL_RISK"
    contract_structure: str = "ALL_STRUCT"
    hedge_designation: str = "ALL_DESIGNATION"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstrumentEdge:
        """Create an InstrumentEdge from raw dictionary mapping."""
        return cls(
            child_instrument=str(data["child_instrument"]),
            parent_instrument=str(data["parent_instrument"]),
            relation_type=str(data.get("relation_type", "SUBTYPE_OF")),
            description=str(data.get("description", "")),
            underlying_risk=str(data.get("underlying_risk", "ALL_RISK")),
            contract_structure=str(data.get("contract_structure", "ALL_STRUCT")),
            hedge_designation=str(data.get("hedge_designation", "ALL_DESIGNATION")),
        )


@dataclass(frozen=True, slots=True)
class ValuationRule:
    """Valuation basis and fair value hierarchy rule."""

    member_pattern: str
    hierarchy_level: str
    implies_valuation_basis: str
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValuationRule:
        """Create a ValuationRule from raw dictionary mapping."""
        return cls(
            member_pattern=str(data["member_pattern"]).lower(),
            hierarchy_level=str(data["hierarchy_level"]),
            implies_valuation_basis=str(data["implies_valuation_basis"]),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class SubspaceInvariant:
    """Multidimensional algebraic routing rule based on feature coordinates."""

    rule_id: str
    measure: str
    book: str
    instrument_ancestor: str
    target_node: str
    algebraic_weight: float = 1.0
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubspaceInvariant:
        """Create a SubspaceInvariant from raw dictionary mapping."""
        return cls(
            rule_id=str(data["rule_id"]),
            measure=str(data["measure"]),
            book=str(data["book"]),
            instrument_ancestor=str(data["instrument_ancestor"]),
            target_node=str(data["target_node"]),
            algebraic_weight=float(data.get("algebraic_weight", 1.0)),
            description=str(data.get("description", "")),
        )


def load_geography_dag(source: Path) -> tuple[GeoHierarchyEdge, ...]:
    """Load geography hierarchy edges from CSV or JSON file."""
    records = read_records(source)
    return tuple(GeoHierarchyEdge.from_dict(row) for row in records)


def load_industry_profiles(source: Path) -> tuple[IndustryProfile, ...]:
    """Load industry classification profiles from JSON or CSV file."""
    records = read_records(source)
    return tuple(IndustryProfile.from_dict(row) for row in records)


def load_axis_families(source: Path) -> tuple[AxisFamilyMapping, ...]:
    """Load axis family mappings taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(AxisFamilyMapping.from_dict(row) for row in records)


@dataclass(frozen=True, slots=True)
class MovementValence:
    """Declared sign of one movement role within a rollforward scope."""

    scope: str
    role: str
    side: str | None
    sign: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MovementValence:
        """Create a MovementValence from raw dictionary mapping."""
        side = data.get("side")
        return cls(
            scope=str(data["scope"]),
            role=str(data["role"]),
            side=str(side) if side is not None else None,
            sign=float(data["sign"]),
        )


def load_valences(source: Path) -> tuple[MovementValence, ...]:
    """Load movement valence records from JSON or CSV file."""
    records = read_records(source)
    return tuple(MovementValence.from_dict(row) for row in records)


@dataclass(frozen=True, slots=True)
class QueryAlias:
    """Declared atom-coordinate targets for a query alias term."""

    alias: str
    targets: tuple[Atom, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryAlias:
        """Create a QueryAlias from raw dictionary mapping."""
        return cls(
            alias=str(data["alias"]),
            targets=tuple(
                Atom(
                    head=str(target["head"]),
                    modifiers=frozenset(str(m) for m in target.get("modifiers", ())),
                )
                for target in data.get("targets", ())
            ),
        )


def load_query_aliases(source: Path) -> tuple[QueryAlias, ...]:
    """Load query alias declarations from JSON or CSV file."""
    records = read_records(source)
    return tuple(QueryAlias.from_dict(row) for row in records)


def load_units(source: Path) -> tuple[UnitMapping, ...]:
    """Load unit mappings taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(UnitMapping.from_dict(row) for row in records)


def load_grammatical_frames(source: Path) -> tuple[GrammaticalFrame, ...]:
    """Load grammatical frames taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(GrammaticalFrame.from_dict(row) for row in records)


def load_member_roles(source: Path) -> tuple[MemberRoleMapping, ...]:
    """Load member roles taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(MemberRoleMapping.from_dict(row) for row in records)


def load_instruments_dag(source: Path) -> tuple[InstrumentEdge, ...]:
    """Load instruments DAG taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(InstrumentEdge.from_dict(row) for row in records)


def load_valuation_rules(source: Path) -> tuple[ValuationRule, ...]:
    """Load valuation rules taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(ValuationRule.from_dict(row) for row in records)


def load_subspace_invariants(source: Path) -> tuple[SubspaceInvariant, ...]:
    """Load subspace invariants taxonomy from JSON or CSV file."""
    records = read_records(source)
    return tuple(SubspaceInvariant.from_dict(row) for row in records)
