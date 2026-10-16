"""Sub-atomic accounting taxonomy, prime heads, and relational schemas."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.schema.relations import AtomRelationGraph


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
    canonical_concept: str = ""
    recognition_book: str = "B_INCOME_STATEMENT"
    flow_stock: str = "FLOW"
    timing_horizon: str = "DURATION_PERIOD"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimeHead:
        """Create a PrimeHead instance from raw dictionary mapping."""
        rec_book = str(data.get("recognition_book", ""))
        if not rec_book:
            st = str(data.get("statement_type", ""))
            if "BalanceSheet" in st:
                rec_book = "B_BALANCE_SHEET"
            elif "CashFlow" in st:
                rec_book = "B_CASH_FLOW_STATEMENT"
            else:
                rec_book = "B_INCOME_STATEMENT"

        f_stock = str(data.get("flow_stock", ""))
        if not f_stock:
            ec = str(data.get("economic_class", ""))
            f_stock = "STOCK" if ec.startswith("STOCK") else "FLOW"

        t_horizon = str(data.get("timing_horizon", ""))
        if not t_horizon:
            t_horizon = "POINT_IN_TIME" if f_stock == "STOCK" else "DURATION_PERIOD"

        return cls(
            head_id=str(data["head_id"]),
            head_symbol=str(data["head_symbol"]),
            economic_class=str(data["economic_class"]),
            statement_type=str(data["statement_type"]),
            normal_balance=str(data["normal_balance"]),
            is_dual_role_primitive=int(data["is_dual_role_primitive"]),
            description=str(data["description"]),
            canonical_concept=str(data.get("canonical_concept", "")),
            recognition_book=rec_book,
            flow_stock=f_stock,
            timing_horizon=t_horizon,
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
    valuation_basis: str | None = None
    realization_state: str | None = None

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
            valuation_basis=data.get("valuation_basis"),
            realization_state=data.get("realization_state"),
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


@dataclass(frozen=True, slots=True)
class DomainTaxonomy:
    """Aggregated domain taxonomy containing heads, modifiers, and relations."""

    prime_heads: tuple[PrimeHead, ...]
    subatomic_modifiers: tuple[SubatomicModifier, ...]
    token_lexicon: TokenLexicon | None = None
    atom_relations: AtomRelationGraph | None = None
    geography_edges: tuple[GeoHierarchyEdge, ...] = ()
    industry_profiles: tuple[IndustryProfile, ...] = ()
    axis_families: tuple[AxisFamilyMapping, ...] = ()
    units: tuple[UnitMapping, ...] = ()
    grammatical_frames: tuple[GrammaticalFrame, ...] = ()
    member_roles: tuple[MemberRoleMapping, ...] = ()
    instruments_dag: tuple[InstrumentEdge, ...] = ()
    valuation_rules: tuple[ValuationRule, ...] = ()
    subspace_invariants: tuple[SubspaceInvariant, ...] = ()

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

    def classify_axis(self, axis_qname: str) -> str:
        """Classify an axis QName into its canonical semantic family using declarative taxonomy."""
        local = axis_qname.split(":")[-1].lower().removeprefix("statement")
        for mapping in self.axis_families:
            if mapping.axis_pattern.lower() in local:
                return mapping.axis_family
        return "OTHER"

    def find_token_axis(self, token: str) -> tuple[str, str] | None:
        """Find axis family and default axis QName for a scope token from taxonomy."""
        tok_low = token.lower()
        for mapping in self.axis_families:
            if tok_low in mapping.scope_tokens:
                axis_qname = (
                    mapping.default_axis_qname
                    or f"us-gaap:{mapping.axis_family.title()}Axis"
                )
                return mapping.axis_family, axis_qname
        for geo in self.geography_edges:
            child_low = geo.child_geo_node.lower().split(":")[-1].removesuffix("member")
            parent_low = (
                geo.parent_geo_node.lower().split(":")[-1].removesuffix("member")
            )
            if tok_low in (child_low, parent_low):
                return "GEOGRAPHY", "us-gaap:StatementGeographicalAxis"
        return None

    def resolve_geography(
        self,
        token_or_qname: str,
        firm_domicile: str = "US",
    ) -> GeoResolution | None:
        """Resolve raw token or node against geography DAG and firm domicile."""
        t_clean = token_or_qname.strip()
        t_low = t_clean.lower().split(":")[-1].removesuffix("member")
        domicile_node = f"country:{firm_domicile.upper()}"
        domicile_low = firm_domicile.lower()

        target_node: str | None = None
        for edge in self.geography_edges:
            c_low = edge.child_geo_node.lower().split(":")[-1].removesuffix("member")
            p_low = edge.parent_geo_node.lower().split(":")[-1].removesuffix("member")
            if t_clean in (edge.child_geo_node, edge.parent_geo_node):
                target_node = (
                    edge.child_geo_node
                    if t_clean == edge.child_geo_node
                    else edge.parent_geo_node
                )
                break
            if t_low in (c_low, p_low):
                target_node = (
                    edge.child_geo_node if t_low == c_low else edge.parent_geo_node
                )
                break

        if target_node is None and self.token_lexicon is not None:
            matches, _ = self.token_lexicon.scan_tokens((t_clean,))
            for m in matches:
                if m.entry.role == "INDEXICAL":
                    if m.entry.indexical == "DOMICILE":
                        target_node = domicile_node
                        break
                    if m.entry.indexical == "FOREIGN":
                        target_node = "srt:ForeignMember"
                        break

        if target_node is None:
            return None

        is_domestic = target_node == domicile_node
        is_foreign = not is_domestic

        ancestors: list[str] = []
        schemes: list[str] = []
        frontier = [target_node]
        visited = {target_node}
        while frontier:
            curr = frontier.pop(0)
            for edge in self.geography_edges:
                if edge.child_geo_node == curr:
                    if edge.parent_geo_node not in visited:
                        visited.add(edge.parent_geo_node)
                        frontier.append(edge.parent_geo_node)
                        ancestors.append(edge.parent_geo_node)
                    if edge.decomposition_scheme not in schemes:
                        schemes.append(edge.decomposition_scheme)

        return GeoResolution(
            canonical_node=target_node,
            is_domestic=is_domestic,
            is_foreign=is_foreign,
            ancestor_regions=tuple(ancestors),
            decomposition_schemes=tuple(schemes),
        )

    def match_grammatical_frame(
        self,
        tokens: tuple[str, ...],
    ) -> GrammaticalFrame | None:
        """Match token sequence against declarative grammatical frames."""
        tokens_low = [t.lower() for t in tokens]
        for frame in self.grammatical_frames:
            k = len(frame.prefix_tokens)
            if len(tokens_low) >= k and tuple(tokens_low[:k]) == frame.prefix_tokens:
                return frame
        return None

    def classify_member_role(self, member_qname: str) -> str:
        """Classify dimension member role using declarative taxonomy patterns."""
        local = member_qname.split(":")[-1].lower()
        for mapping in self.member_roles:
            if mapping.pattern in local:
                return mapping.role
        return "NORMAL"

    def is_instrument_subtype(self, child: str, parent: str) -> bool:
        """Check if child instrument is equal to or a subtype of parent instrument."""
        c_clean = child.split(":")[-1].lower()
        p_clean = parent.split(":")[-1].lower()
        if c_clean == p_clean:
            return True
        c_edge = next(
            (
                e
                for e in self.instruments_dag
                if e.relation_type == "SUBTYPE_OF"
                and e.child_instrument.split(":")[-1].lower() == c_clean
            ),
            None,
        )
        p_edge = next(
            (
                e
                for e in self.instruments_dag
                if e.relation_type == "SUBTYPE_OF"
                and e.child_instrument.split(":")[-1].lower() == p_clean
            ),
            None,
        )
        if (
            c_edge
            and p_edge
            and c_edge.contract_structure != "ALL_STRUCT"
            and p_edge.contract_structure != "ALL_STRUCT"
        ):
            if c_edge.contract_structure != p_edge.contract_structure:
                return False
        frontier = [child]
        visited = {child}
        while frontier:
            curr = frontier.pop(0)
            curr_clean = curr.split(":")[-1].lower()
            if curr_clean == p_clean:
                return True
            for edge in self.instruments_dag:
                if edge.relation_type != "SUBTYPE_OF":
                    continue
                edge_c = edge.child_instrument.split(":")[-1].lower()
                if edge_c == curr_clean and edge.parent_instrument not in visited:
                    visited.add(edge.parent_instrument)
                    frontier.append(edge.parent_instrument)
        return False

    def are_contract_structures_exclusive(
        self, structure_a: str, structure_b: str
    ) -> bool:
        """Check declared mutual exclusion between contract structures."""
        return any(
            edge.relation_type == "MUTUALLY_EXCLUSIVE"
            and {edge.child_instrument, edge.parent_instrument}
            == {structure_a.upper(), structure_b.upper()}
            for edge in self.instruments_dag
        )

    def resolve_valuation_basis(self, member_qname: str) -> tuple[str, str]:
        """Resolve hierarchy level and valuation basis for a dimension member."""
        local = member_qname.split(":")[-1].lower()
        for rule in self.valuation_rules:
            if rule.member_pattern in local:
                return rule.hierarchy_level, rule.implies_valuation_basis
        return "UNSPECIFIED", "HISTORICAL_COST"

    def match_subspace_invariant(
        self,
        measure: str,
        book: str,
        instrument: str | None = None,
    ) -> SubspaceInvariant | None:
        """Match coordinate features against multidimensional algebraic routing rules."""
        m_clean = measure.split(":")[-1]
        for rule in self.subspace_invariants:
            if rule.measure == m_clean and rule.book == book:
                if instrument is None:
                    return rule
                if self.is_instrument_subtype(instrument, rule.instrument_ancestor):
                    return rule
        return None

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
        """Find concepts equivalent by coordinate identity in the atom lattice."""
        target = concept.split(":")[-1]
        return {concept, target}


@dataclass(frozen=True, slots=True)
class SemanticConceptFrame:
    """Decomposed semantic slots and prime head classification for an XBRL concept."""

    qname: str
    prime_head: str
    modifiers: tuple[str, ...] = ()
    atom: Atom | None = None
    residual_tokens: tuple[str, ...] = ()
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


def load_grammatical_frames(source: Path) -> tuple[GrammaticalFrame, ...]:
    """Load grammatical frames taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(GrammaticalFrame.from_dict(row) for row in records)


def load_member_roles(source: Path) -> tuple[MemberRoleMapping, ...]:
    """Load member roles taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(MemberRoleMapping.from_dict(row) for row in records)


def load_instruments_dag(source: Path) -> tuple[InstrumentEdge, ...]:
    """Load instruments DAG taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(InstrumentEdge.from_dict(row) for row in records)


def load_valuation_rules(source: Path) -> tuple[ValuationRule, ...]:
    """Load valuation rules taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(ValuationRule.from_dict(row) for row in records)


def load_subspace_invariants(source: Path) -> tuple[SubspaceInvariant, ...]:
    """Load subspace invariants taxonomy from JSON or CSV file."""
    records = _read_records(source)
    return tuple(SubspaceInvariant.from_dict(row) for row in records)


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
    lexicon_p = base_dir / x_paths.default_token_lexicon_path.name
    rels_p = base_dir / x_paths.default_atom_relations_path.name
    types_p = base_dir / x_paths.default_relation_types_path.name
    geo_p = base_dir / x_paths.default_geography_path.name
    ind_p = base_dir / x_paths.default_industries_path.name
    axis_p = base_dir / x_paths.default_axis_families_path.name
    unit_p = base_dir / x_paths.default_units_path.name
    frame_p = base_dir / x_paths.default_grammatical_frames_path.name
    role_p = base_dir / x_paths.default_member_roles_path.name
    inst_p = base_dir / x_paths.default_instruments_dag_path.name
    val_p = base_dir / x_paths.default_valuation_rules_path.name
    sub_p = base_dir / x_paths.default_subspace_invariants_path.name

    if not heads_p.is_file():
        raise FileNotFoundError(f"missing prime_heads in {base_dir}")
    if not mods_p.is_file():
        raise FileNotFoundError(f"missing subatomic_modifiers in {base_dir}")

    token_lexicon = TokenLexicon.load_json(lexicon_p) if lexicon_p.is_file() else None
    atom_relations = (
        AtomRelationGraph.load_json(rels_p, types_p) if rels_p.is_file() else None
    )

    return DomainTaxonomy(
        prime_heads=load_prime_heads(heads_p),
        subatomic_modifiers=load_subatomic_modifiers(mods_p),
        token_lexicon=token_lexicon,
        atom_relations=atom_relations,
        geography_edges=load_geography_dag(geo_p) if geo_p.is_file() else (),
        industry_profiles=load_industry_profiles(ind_p) if ind_p.is_file() else (),
        axis_families=load_axis_families(axis_p) if axis_p.is_file() else (),
        units=load_units(unit_p) if unit_p.is_file() else (),
        grammatical_frames=load_grammatical_frames(frame_p)
        if frame_p.is_file()
        else (),
        member_roles=load_member_roles(role_p) if role_p.is_file() else (),
        instruments_dag=load_instruments_dag(inst_p) if inst_p.is_file() else (),
        valuation_rules=load_valuation_rules(val_p) if val_p.is_file() else (),
        subspace_invariants=load_subspace_invariants(sub_p) if sub_p.is_file() else (),
    )
