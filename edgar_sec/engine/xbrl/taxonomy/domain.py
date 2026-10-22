"""Aggregated domain taxonomy: heads, modifiers, records, and relations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.normalize.temporal import TemporalInterval
from edgar_sec.engine.xbrl.schema.relations import AtomRelationGraph
from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate, load_defaults
from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
    PrimeHead,
    SiblingGroup,
    SubatomicModifier,
    load_prime_heads,
    load_sibling_groups,
    load_subatomic_modifiers,
)
from edgar_sec.engine.xbrl.taxonomy.records import (
    AxisFamilyMapping,
    GeoHierarchyEdge,
    GeoResolution,
    GrammaticalFrame,
    IndustryProfile,
    InstrumentEdge,
    MemberRoleMapping,
    SubspaceInvariant,
    UnitMapping,
    ValuationRule,
    load_axis_families,
    load_geography_dag,
    load_grammatical_frames,
    load_industry_profiles,
    load_instruments_dag,
    load_member_roles,
    load_subspace_invariants,
    load_units,
    load_valuation_rules,
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
    default_coordinates: tuple[DefaultCoordinate, ...] = ()
    sibling_groups: tuple[SiblingGroup, ...] = ()

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

    def axis_group(self, group: str) -> SiblingGroup | None:
        """Lookup a declared sibling-axis group by name."""
        for declared in self.sibling_groups:
            if declared.group == group:
                return declared
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
                if m.entry.claim == "indexical":
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

    def resolve_instrument_risk(self, instrument_or_member: str) -> str | None:
        """Resolve canonical underlying risk type via graph traversal on instruments DAG."""
        risk_map = {
            "IR": "interest_rate",
            "FX": "foreign_exchange",
            "CP": "credit",
            "EQ": "equity",
            "CM": "commodity",
        }
        target = instrument_or_member.split(":")[-1].lower()
        frontier = [target]
        visited = {target}
        while frontier:
            curr = frontier.pop(0)
            for edge in self.instruments_dag:
                c_clean = edge.child_instrument.split(":")[-1].lower()
                if c_clean == curr:
                    if edge.underlying_risk in risk_map:
                        return risk_map[edge.underlying_risk]
                    p_clean = edge.parent_instrument.split(":")[-1].lower()
                    if p_clean not in visited:
                        visited.add(p_clean)
                        frontier.append(p_clean)
        return None

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
    indexicals: tuple[str, ...] = ()
    temporal: TemporalInterval | None = None


def validate_domain_taxonomy(taxonomy: DomainTaxonomy) -> None:
    """Refuse a taxonomy whose declared structure contradicts its data.

    Kinds on every def, the groups table matching def declarations,
    and every lexicon-asserted id defined.
    """
    defs = {m.modifier_id: m for m in taxonomy.subatomic_modifiers}
    for mod in taxonomy.subatomic_modifiers:
        if not mod.kinds:
            raise ValueError(f"modifier {mod.modifier_id} declares no kinds")
        for kind in mod.kinds:
            if kind not in (
                "IDENTITY",
                "AXIS",
                "STRUCTURAL",
                "VALUATION",
                "SCOPE",
                "CONTEXT",
            ):
                raise ValueError(f"modifier {mod.modifier_id} has unknown kind {kind}")
    declared: dict[str, set[str]] = {}
    for mod in taxonomy.subatomic_modifiers:
        if mod.sibling_group:
            declared.setdefault(mod.sibling_group, set()).add(mod.modifier_id)
    table = {g.group: set(g.members) for g in taxonomy.sibling_groups}
    if declared != table:
        raise ValueError(
            f"sibling groups table {table} contradicts def declarations {declared}"
        )
    head_ids = {h.head_id for h in taxonomy.prime_heads}
    if taxonomy.token_lexicon is not None:
        for entry in taxonomy.token_lexicon.entries:
            unknown = entry.asserted_modifier_ids() - set(defs)
            if unknown:
                raise ValueError(
                    f"lexicon entry {entry.phrase} asserts undef'd modifiers {unknown}"
                )
            if entry.claim == "head" and entry.head not in head_ids:
                raise ValueError(
                    f"head claim {entry.phrase} names unknown head {entry.head}"
                )


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
    defaults_p = base_dir / x_paths.default_default_coordinates_path.name
    groups_p = base_dir / x_paths.default_sibling_groups_path.name

    if not heads_p.is_file():
        raise FileNotFoundError(f"missing prime_heads in {base_dir}")
    if not mods_p.is_file():
        raise FileNotFoundError(f"missing subatomic_modifiers in {base_dir}")

    token_lexicon = TokenLexicon.load_json(lexicon_p) if lexicon_p.is_file() else None
    atom_relations = (
        AtomRelationGraph.load_json(rels_p, types_p) if rels_p.is_file() else None
    )
    default_coordinates = load_defaults(defaults_p, heads_p, mods_p, token_lexicon)
    taxonomy = DomainTaxonomy(
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
        default_coordinates=default_coordinates,
        sibling_groups=load_sibling_groups(groups_p) if groups_p.is_file() else (),
    )
    if taxonomy.token_lexicon is not None:
        taxonomy.token_lexicon.attach_modifier_kinds(
            {m.modifier_id: m.kinds for m in taxonomy.subatomic_modifiers}
        )
    if taxonomy.sibling_groups:
        validate_domain_taxonomy(taxonomy)
    return taxonomy
