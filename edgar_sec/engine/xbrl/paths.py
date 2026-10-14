"""Artifact and source path layout resolution for the XBRL engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths

XBRL_DIR = "xbrl"
LINKBASES_DIR = "linkbases"
XML_CACHE_DIR = "xml"
DEFAULT_LINKBASES_FILE = "linkbases.parquet"
DEFAULT_SEED_COHORT_FILE = "seed_cohort.json"
TAXONOMY_DIR = "taxonomy"
DEFAULT_PRIME_HEADS_FILE = "prime_heads.json"
DEFAULT_SUBATOMIC_MODIFIERS_FILE = "subatomic_modifiers.json"
DEFAULT_TOKEN_LEXICON_FILE = "token_lexicon.json"
DEFAULT_ATOM_RELATIONS_FILE = "atom_relations.json"
DEFAULT_RELATION_TYPES_FILE = "relation_types.json"
DEFAULT_GEOGRAPHY_FILE = "geography_dag.json"
DEFAULT_INDUSTRIES_FILE = "industries.json"
DEFAULT_AXIS_FAMILIES_FILE = "axis_families.json"
DEFAULT_UNITS_FILE = "units.json"
DEFAULT_GRAMMATICAL_FRAMES_FILE = "grammatical_frames.json"
DEFAULT_MEMBER_ROLES_FILE = "member_roles.json"
DEFAULT_INSTRUMENTS_DAG_FILE = "instruments_dag.json"
DEFAULT_VALUATION_RULES_FILE = "valuation_rules.json"
DEFAULT_SUBSPACE_INVARIANTS_FILE = "subspace_invariants.json"


@dataclass(frozen=True, slots=True)
class XbrlPaths:
    """Path layout for XBRL linkbases, uploads, and cached documents."""

    project: ProjectPaths

    @property
    def artifacts_root(self) -> Path:
        """Root directory for project artifacts."""
        return self.project.artifacts_root

    @property
    def repo_root(self) -> Path:
        """Root directory for the git repository."""
        return self.project.repo_root

    @property
    def uploads_root(self) -> Path:
        """Root directory for uploads and operator inputs."""
        return self.project.uploads_root

    @property
    def xbrl_root(self) -> Path:
        """Root directory for all published XBRL artifacts."""
        return self.artifacts_root / XBRL_DIR

    @property
    def linkbases_dir(self) -> Path:
        """Directory housing linkbase Parquet inventories."""
        return self.xbrl_root / LINKBASES_DIR

    @property
    def xml_cache_dir(self) -> Path:
        """Directory housing cached linkbase XML source files."""
        return self.xbrl_root / XML_CACHE_DIR

    @property
    def default_linkbases_path(self) -> Path:
        """Default linkbase inventory Parquet file path."""
        return self.linkbases_dir / DEFAULT_LINKBASES_FILE

    @property
    def default_seed_cohort_path(self) -> Path:
        """Default path to the clean seed cohort input JSON."""
        return self.default_taxonomy_dir / DEFAULT_SEED_COHORT_FILE

    @property
    def default_taxonomy_dir(self) -> Path:
        """Directory housing accounting domain taxonomy files."""
        return self.repo_root / "edgar_sec" / "engine" / XBRL_DIR / TAXONOMY_DIR

    @property
    def default_prime_heads_path(self) -> Path:
        """Default path to prime heads taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_PRIME_HEADS_FILE

    @property
    def default_subatomic_modifiers_path(self) -> Path:
        """Default path to subatomic modifiers taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_SUBATOMIC_MODIFIERS_FILE

    @property
    def default_token_lexicon_path(self) -> Path:
        """Default path to token lexicon taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_TOKEN_LEXICON_FILE

    @property
    def default_atom_relations_path(self) -> Path:
        """Default path to atom relations taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_ATOM_RELATIONS_FILE

    @property
    def default_relation_types_path(self) -> Path:
        """Default path to relation types taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_RELATION_TYPES_FILE

    @property
    def default_geography_path(self) -> Path:
        """Default path to geography DAG taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_GEOGRAPHY_FILE

    @property
    def default_industries_path(self) -> Path:
        """Default path to industry profiles taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_INDUSTRIES_FILE

    @property
    def default_axis_families_path(self) -> Path:
        """Default path to axis families taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_AXIS_FAMILIES_FILE

    @property
    def default_units_path(self) -> Path:
        """Default path to units taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_UNITS_FILE

    @property
    def default_grammatical_frames_path(self) -> Path:
        """Default path to grammatical frames taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_GRAMMATICAL_FRAMES_FILE

    @property
    def default_member_roles_path(self) -> Path:
        """Default path to member roles taxonomy file."""
        return self.default_taxonomy_dir / DEFAULT_MEMBER_ROLES_FILE

    @property
    def default_instruments_dag_path(self) -> Path:
        """Default path to financial instruments DAG file."""
        return self.default_taxonomy_dir / DEFAULT_INSTRUMENTS_DAG_FILE

    @property
    def default_valuation_rules_path(self) -> Path:
        """Default path to valuation and fair value rules file."""
        return self.default_taxonomy_dir / DEFAULT_VALUATION_RULES_FILE

    @property
    def default_subspace_invariants_path(self) -> Path:
        """Default path to multidimensional subspace routing invariants file."""
        return self.default_taxonomy_dir / DEFAULT_SUBSPACE_INVARIANTS_FILE

    def linkbase_parquet_path(self, cohort_id: str = "seed") -> Path:
        """Return the Parquet path for a named cohort's linkbases."""
        return self.linkbases_dir / f"{cohort_id}_{DEFAULT_LINKBASES_FILE}"

    def ensure_directories(self) -> None:
        """Create artifact directories if they do not exist."""
        self.linkbases_dir.mkdir(parents=True, exist_ok=True)
        self.xml_cache_dir.mkdir(parents=True, exist_ok=True)


def resolve_xbrl_paths(
    repo_root: Path | str | None = None,
    artifacts_root: Path | str | None = None,
) -> XbrlPaths:
    """Resolve XBRL paths against repo root and artifacts root settings."""
    root = Path(repo_root).resolve() if repo_root is not None else None
    project = resolve_paths(root)
    if artifacts_root is not None:
        project = ProjectPaths(
            repo_root=project.repo_root,
            artifacts_root=Path(artifacts_root).resolve(),
            uploads_root=project.uploads_root,
        )
    return XbrlPaths(project)


def default_taxonomy_dir(repo_root: Path | str | None = None) -> Path:
    """Return default directory housing built-in domain taxonomy files."""
    return resolve_xbrl_paths(repo_root=repo_root).default_taxonomy_dir
