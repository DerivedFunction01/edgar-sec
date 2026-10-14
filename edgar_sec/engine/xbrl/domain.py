"""Sub-atomic accounting taxonomy, prime heads, and relational schemas."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PrimeHead:
    """Accounting prime head representation."""

    head_id: str
    head_symbol: str
    economic_class: str
    statement_type: str
    normal_balance: str
    is_dual_role_primitive: int
    description: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimeHead:
        """Create a PrimeHead instance from raw dictionary mapping."""
        return cls(
            head_id=str(data["head_id"]),
            head_symbol=str(data["head_symbol"]),
            economic_class=str(data["economic_class"]),
            statement_type=str(data["statement_type"]),
            normal_balance=str(data["normal_balance"]),
            is_dual_role_primitive=int(data["is_dual_role_primitive"]),
            description=str(data["description"]),
        )

    def to_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        """Convert into canonical raw tuple representation."""
        return (
            self.head_id,
            self.head_symbol,
            self.economic_class,
            self.statement_type,
            self.normal_balance,
            self.is_dual_role_primitive,
            self.description,
        )


@dataclass(frozen=True, slots=True)
class SubatomicModifier:
    """Sub-atomic domain or valuation modifier representation."""

    modifier_id: str
    category: str
    keywords: tuple[str, ...]
    description: str

    @property
    def pattern_keywords(self) -> tuple[str, ...]:
        return self.keywords

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubatomicModifier:
        """Create a SubatomicModifier from raw dictionary mapping."""
        raw_kw = data.get("keywords", ())
        if isinstance(raw_kw, (list, tuple)):
            keywords = tuple(str(k) for k in raw_kw)
        elif isinstance(raw_kw, str):
            clean = raw_kw.replace("|", ";").replace(",", ";")
            keywords = tuple(k.strip() for k in clean.split(";") if k.strip())
        else:
            keywords = ()
        return cls(
            modifier_id=str(data["modifier_id"]),
            category=str(data["category"]),
            keywords=keywords,
            description=str(data["description"]),
        )

    def to_tuple(self) -> tuple[str, str, tuple[str, ...], str]:
        """Convert into canonical raw tuple representation."""
        return (
            self.modifier_id,
            self.category,
            self.keywords,
            self.description,
        )


@dataclass(frozen=True, slots=True)
class TypedRelation:
    """Typed relational edge representation."""

    edge_id: str
    source_node: str
    target_node: str
    relation_type: str
    algebraic_weight: float
    sic_scope: str
    description: str
    formula_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TypedRelation:
        """Create a TypedRelation from raw dictionary mapping."""
        return cls(
            edge_id=str(data["edge_id"]),
            source_node=str(data["source_node"]),
            target_node=str(data["target_node"]),
            relation_type=str(data["relation_type"]),
            algebraic_weight=float(data["algebraic_weight"]),
            sic_scope=str(data["sic_scope"]),
            description=str(data["description"]),
            formula_id=str(data["formula_id"]) if data.get("formula_id") else None,
        )

    def to_tuple(self) -> tuple[str, str, str, str, float, str, str, str | None]:
        """Convert into canonical raw tuple representation."""
        return (
            self.edge_id,
            self.source_node,
            self.target_node,
            self.relation_type,
            self.algebraic_weight,
            self.sic_scope,
            self.description,
            self.formula_id,
        )


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
    """Mapping of axis pattern to canonical axis family."""

    axis_pattern: str
    axis_family: str
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AxisFamilyMapping:
        """Create an AxisFamilyMapping from raw dictionary mapping."""
        return cls(
            axis_pattern=str(data["axis_pattern"]),
            axis_family=str(data["axis_family"]),
            description=str(data.get("description", "")),
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
class DomainTaxonomy:
    """Aggregated domain taxonomy containing heads, modifiers, and relations."""

    prime_heads: tuple[PrimeHead, ...]
    subatomic_modifiers: tuple[SubatomicModifier, ...]
    typed_relations: tuple[TypedRelation, ...]
    geography_edges: tuple[GeoHierarchyEdge, ...] = ()
    industry_profiles: tuple[IndustryProfile, ...] = ()
    axis_families: tuple[AxisFamilyMapping, ...] = ()
    units: tuple[UnitMapping, ...] = ()

    def prime_head(self, head_id: str) -> PrimeHead | None:
        """Lookup a prime head by unique identifier."""
        for head in self.prime_heads:
            if head.head_id == head_id:
                return head
        return None

    def modifier(self, modifier_id: str) -> SubatomicModifier | None:
        """Lookup a modifier by unique identifier."""
        for mod in self.subatomic_modifiers:
            if mod.modifier_id == modifier_id:
                return mod
        return None

    def industry_profile(self, firm_id: str) -> IndustryProfile | None:
        """Lookup an industry profile by firm identifier."""
        target = firm_id.upper()
        for prof in self.industry_profiles:
            if prof.firm_id.upper() == target:
                return prof
        return None

    def find_industry(self, firm_id: str) -> IndustryProfile | None:
        """Lookup an industry profile by ticker or firm identifier."""
        return self.industry_profile(firm_id)

    def find_head_placement(
        self,
        head_id: str,
        sector: str = "",
    ) -> TypedRelation | None:
        """Find default placement edge for a prime head from the taxonomy graph."""
        sector_match: TypedRelation | None = None
        universal_match: TypedRelation | None = None
        for edge in self.typed_relations:
            if edge.source_node == head_id:
                if sector and edge.sic_scope == sector:
                    sector_match = edge
                elif edge.sic_scope in ("ALL", "*"):
                    universal_match = edge
        return sector_match or universal_match

    def classify_axis(self, axis_qname: str) -> str:
        """Classify an axis QName into its canonical semantic family using declarative taxonomy."""
        local = axis_qname.split(":")[-1].lower().removeprefix("statement")
        for mapping in self.axis_families:
            if mapping.axis_pattern.lower() in local:
                return mapping.axis_family
        return "OTHER"

    def normalize_unit(self, unit: str | None) -> str:
        """Normalize raw XBRL unit token using declarative taxonomy."""
        if not unit:
            return "PURE"
        u_clean = unit.strip().upper()
        for mapping in self.units:
            if mapping.raw_unit.upper() == u_clean:
                return mapping.unit_class
        return u_clean

    def equivalent_concepts(self, concept: str) -> set[str]:
        """Find all equivalent concepts connected via SAME_CONCEPT or ALIAS_OF edges."""
        target = concept.split(":")[-1]
        equivalences: set[str] = {concept, target}
        changed = True
        while changed:
            changed = False
            for edge in self.typed_relations:
                if edge.relation_type in ("SAME_CONCEPT", "EQUIVALENT_TO", "ALIAS_OF"):
                    src = edge.source_node.split(":")[-1]
                    tgt = edge.target_node.split(":")[-1]
                    if (src in equivalences or edge.source_node in equivalences) and (
                        tgt not in equivalences
                    ):
                        equivalences.add(tgt)
                        equivalences.add(edge.target_node)
                        changed = True
                    elif (tgt in equivalences or edge.target_node in equivalences) and (
                        src not in equivalences
                    ):
                        equivalences.add(src)
                        equivalences.add(edge.source_node)
                        changed = True
        return equivalences


@dataclass(frozen=True, slots=True)
class SemanticConceptFrame:
    """Decomposed semantic slots and prime head classification for an XBRL concept."""

    qname: str
    prime_head: str
    modifiers: tuple[str, ...] = ()
    recognition_book: str = "B_INCOME_STATEMENT"
    flow_stock: str = "FLOW"
    timing_horizon: str = "DURATION_PERIOD"
    valuation_basis: str = "HISTORICAL_AMORTIZED_COST"
    realization_state: str = "REALIZED_P_L"
    polarity: str = "NEUTRAL"
    expected_weight: int = 1


def _read_records(source: Path) -> list[dict[str, Any]]:
    if source.suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"expected list of records in {source}")
        return [dict(item) for item in payload]
    delimiter = "\t" if source.suffix == ".tsv" else ","
    with source.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        return [dict(row) for row in reader]


def load_prime_heads(source: Path) -> tuple[PrimeHead, ...]:
    """Load prime heads taxonomy from JSON, CSV, or TSV file."""
    records = _read_records(source)
    return tuple(PrimeHead.from_dict(row) for row in records)


def load_subatomic_modifiers(source: Path) -> tuple[SubatomicModifier, ...]:
    """Load subatomic modifiers taxonomy from JSON, CSV, or TSV file."""
    records = _read_records(source)
    return tuple(SubatomicModifier.from_dict(row) for row in records)


def load_typed_relations(source: Path) -> tuple[TypedRelation, ...]:
    """Load typed relations taxonomy from JSON, CSV, or TSV file."""
    records = _read_records(source)
    return tuple(TypedRelation.from_dict(row) for row in records)


def load_geography_dag(source: Path) -> tuple[GeoHierarchyEdge, ...]:
    """Load geography hierarchy edges from CSV or JSON file."""
    records = _read_records(source)
    return tuple(GeoHierarchyEdge.from_dict(row) for row in records)


def load_industry_profiles(source: Path) -> tuple[IndustryProfile, ...]:
    """Load industry classification profiles from JSON or CSV file."""
    records = _read_records(source)
    return tuple(IndustryProfile.from_dict(row) for row in records)


def load_axis_families(source: Path) -> tuple[AxisFamilyMapping, ...]:
    """Load axis family mappings taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(AxisFamilyMapping.from_dict(row) for row in records)


def load_units(source: Path) -> tuple[UnitMapping, ...]:
    """Load unit mappings taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(UnitMapping.from_dict(row) for row in records)


def load_domain_taxonomy(
    taxonomy_source: Any | None = None,
) -> DomainTaxonomy:
    """Load full domain taxonomy using XbrlPaths layout resolution."""
    from edgar_sec.engine.xbrl.paths import XbrlPaths, resolve_xbrl_paths

    if isinstance(taxonomy_source, (str, Path)):
        base_dir = Path(taxonomy_source)
        x_paths = resolve_xbrl_paths()
    elif isinstance(taxonomy_source, XbrlPaths):
        x_paths = taxonomy_source
        base_dir = x_paths.default_taxonomy_dir
    else:
        x_paths = resolve_xbrl_paths()
        base_dir = x_paths.default_taxonomy_dir

    heads_p = base_dir / x_paths.default_prime_heads_path.name
    mods_p = base_dir / x_paths.default_subatomic_modifiers_path.name
    rels_p = base_dir / x_paths.default_typed_relations_path.name
    geo_p = base_dir / x_paths.default_geography_path.name
    ind_p = base_dir / x_paths.default_industries_path.name
    axis_p = base_dir / x_paths.default_axis_families_path.name
    unit_p = base_dir / x_paths.default_units_path.name

    if not heads_p.is_file():
        raise FileNotFoundError(f"missing prime_heads in {base_dir}")
    if not mods_p.is_file():
        raise FileNotFoundError(f"missing subatomic_modifiers in {base_dir}")
    if not rels_p.is_file():
        raise FileNotFoundError(f"missing typed_relations in {base_dir}")

    return DomainTaxonomy(
        prime_heads=load_prime_heads(heads_p),
        subatomic_modifiers=load_subatomic_modifiers(mods_p),
        typed_relations=load_typed_relations(rels_p),
        geography_edges=load_geography_dag(geo_p) if geo_p.is_file() else (),
        industry_profiles=load_industry_profiles(ind_p) if ind_p.is_file() else (),
        axis_families=load_axis_families(axis_p) if axis_p.is_file() else (),
        units=load_units(unit_p) if unit_p.is_file() else (),
    )
