"""Mining fact concept token sequences and n-grams across grounded fixtures."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path

import pyarrow as pa

from edgar_sec.engine.xbrl.evidence.mining import CollocationMiner, SupportCounter
from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept_expression,
    split_camel_case,
)
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.solve.equivalence import presumed_atom
from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate


@dataclass(frozen=True, slots=True)
class FactTaxonomyCoverageReport:
    """Empirical coverage metrics of existing taxonomy against reported facts."""

    total_facts: int
    unique_concepts: int
    total_tokens: int
    covered_tokens: int
    token_coverage_ratio: float
    top_oov_tokens: tuple[tuple[str, int], ...]
    top_ngrams: tuple[tuple[tuple[str, ...], int], ...]
    top_oov_ngrams: tuple[tuple[tuple[str, ...], int], ...]


def tokenize_fact_concept(concept_qname: str) -> list[str]:
    """Tokenize a concept QName into normalized lowercased word stems."""
    local = concept_qname.split(":")[-1]
    tokens: list[str] = []
    current: list[str] = []

    for i, ch in enumerate(local):
        if not ch.isalnum():
            if current:
                tokens.append("".join(current).lower())
                current = []
            continue
        if (
            ch.isupper()
            and current
            and (
                i + 1 < len(local)
                and local[i + 1].islower()
                or not current[-1].isupper()
            )
        ):
            tokens.append("".join(current).lower())
            current = [ch]
        else:
            current.append(ch)

    if current:
        tokens.append("".join(current).lower())
    return [t for t in tokens if t]


def mine_fact_token_ngrams(
    facts_table: pa.Table,
    n_range: tuple[int, int] = (2, 4),
) -> dict[tuple[str, ...], int]:
    """Extract and frequency-rank fact concept token n-grams across facts."""
    if "concept_qname" not in facts_table.column_names:
        return {}

    qnames = facts_table.column("concept_qname").to_pylist()
    counts: Counter[tuple[str, ...]] = Counter()

    for qname in set(qnames):
        tokens = tokenize_fact_concept(qname)
        for n in range(n_range[0], n_range[1] + 1):
            if len(tokens) >= n:
                for idx in range(len(tokens) - n + 1):
                    ngram = tuple(tokens[idx : idx + n])
                    counts[ngram] += 1

    return dict(counts.most_common())


def evaluate_taxonomy_fact_coverage(
    facts_table: pa.Table,
    lexicon_path: Path | None = None,
    top_k: int = 20,
) -> FactTaxonomyCoverageReport:
    """Measure token and n-gram coverage of token_lexicon against reported facts."""
    lex_path = lexicon_path or resolve_xbrl_paths().default_token_lexicon_path
    lexicon_data = json.loads(lex_path.read_text(encoding="utf-8"))

    known_tokens: set[str] = set()
    known_phrases: set[tuple[str, ...]] = set()

    for entry in lexicon_data:
        phrase = tuple(p.lower() for p in entry.get("phrase", []))
        if phrase:
            known_phrases.add(phrase)
            for word in phrase:
                known_tokens.add(word)

    qnames = facts_table.column("concept_qname").to_pylist()
    unique_qnames = sorted(set(qnames))

    total_tokens = 0
    covered_tokens = 0
    oov_token_counter: Counter[str] = Counter()
    ngram_counter: Counter[tuple[str, ...]] = Counter()
    oov_ngram_counter: Counter[tuple[str, ...]] = Counter()

    for qname in unique_qnames:
        tokens = tokenize_fact_concept(qname)
        total_tokens += len(tokens)

        for tok in tokens:
            if tok in known_tokens:
                covered_tokens += 1
            else:
                oov_token_counter[tok] += 1

        for n in (2, 3):
            if len(tokens) >= n:
                for idx in range(len(tokens) - n + 1):
                    ngram = tuple(tokens[idx : idx + n])
                    ngram_counter[ngram] += 1
                    if ngram not in known_phrases and not all(
                        t in known_tokens for t in ngram
                    ):
                        oov_ngram_counter[ngram] += 1

    ratio = (covered_tokens / total_tokens) if total_tokens > 0 else 0.0

    return FactTaxonomyCoverageReport(
        total_facts=len(facts_table),
        unique_concepts=len(unique_qnames),
        total_tokens=total_tokens,
        covered_tokens=covered_tokens,
        token_coverage_ratio=ratio,
        top_oov_tokens=tuple(oov_token_counter.most_common(top_k)),
        top_ngrams=tuple(ngram_counter.most_common(top_k)),
        top_oov_ngrams=tuple(oov_ngram_counter.most_common(top_k)),
    )


@dataclass(frozen=True, slots=True)
class BundleFacts:
    """One seed bundle's fact and arc tables with its firm and SIC identity."""

    firm: str
    sic_code: str
    facts: pa.Table
    calculation_arcs: pa.Table | None = None
    presentation_arcs: pa.Table | None = None


@dataclass(frozen=True, slots=True)
class ConceptModelledness:
    """How completely one concept is modelled by the token lexicon."""

    qname: str
    namespace: str
    token_count: int
    residual_tokens: tuple[str, ...]
    head: str
    modifiers: tuple[str, ...]
    atom: str
    collision_group_size: int
    firm_count: int
    sic_count: int
    fact_rows: int
    calculation_degree: int
    presentation_degree: int
    bucket: str
    statement_slice: str
    residual_class: str = "intent_bearing"
    explained_share: float = 0.0
    adequacy: str = "unmodelled"
    has_identity: bool = False
    derived_horizon: str = ""
    presumed_modifier: str = ""


@dataclass(frozen=True, slots=True)
class ResidualCollocation:
    """A recurrent residual token sequence: a candidate phrase merge."""

    phrase: tuple[str, ...]
    frequency: int
    pmi: float | None
    firm_count: int
    sic_count: int
    structural: bool
    example_qname: str


@dataclass(frozen=True, slots=True)
class FrameConflict:
    """A concept whose fact period profile opposes its head's statement frame."""

    qname: str
    head: str
    head_slice: str
    period_profile: str
    instant_facts: int
    duration_facts: int
    placement_slices: tuple[str, ...]
    firm_count: int


@dataclass(frozen=True, slots=True)
class IdentityCollision:
    """One atom shared by many distinct concepts, with members' residuals."""

    atom: str
    concept_count: int
    members: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class PatternGroup:
    """One decomposed signature recurring across firms and namespaces."""

    head: str
    modifiers: tuple[str, ...]
    residual_signature: tuple[str, ...]
    firms: tuple[str, ...]
    sics: tuple[str, ...]
    concept_count: int
    fact_rows: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModellednessReport:
    """Corpus-wide modelled-ness audit over a set of seed bundles."""

    total_concepts: int
    total_fact_rows: int
    unknown_head_concepts: int
    us_gaap_unknown_non_textblock: int
    long_and_bare_us_gaap: int
    bucket_counts: tuple[tuple[str, int], ...]
    candidate_slice_counts: tuple[tuple[str, int], ...]
    collision_groups: tuple[tuple[str, int, tuple[str, ...]], ...]
    candidates: tuple[ConceptModelledness, ...]
    concepts: tuple[ConceptModelledness, ...]
    residual_collocations: tuple[ResidualCollocation, ...] = ()
    us_gaap_unknown_noise_only: int = 0
    long_and_bare_noise_only: int = 0
    residual_noise_token_total: int = 0
    residual_intent_token_total: int = 0
    frame_conflicts: tuple[FrameConflict, ...] = ()
    adequacy_counts: tuple[tuple[str, int], ...] = ()
    identity_collisions: tuple[IdentityCollision, ...] = ()
    pattern_groups: tuple[PatternGroup, ...] = ()


def _arc_degrees(table: pa.Table | None) -> Counter:
    """Count arc endpoints per concept in one arc table."""
    degrees: Counter = Counter()
    if table is None or "parent_qname" not in table.column_names:
        return degrees
    for parent, child in zip(
        table.column("parent_qname").to_pylist(),
        table.column("child_qname").to_pylist(),
    ):
        degrees[parent] += 1
        degrees[child] += 1
    return degrees


_STRUCTURAL_TOKENS = frozenset(
    {"text", "block", "table", "policy", "disclosure", "extensible", "enumeration"}
)

_NOISE_RESIDUAL_TOKENS = _STRUCTURAL_TOKENS | frozenset(
    {
        "schedule",
        "statement",
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "to",
        "for",
        "by",
        "from",
        "at",
        "as",
        "with",
        "under",
        "over",
        "before",
        "after",
        "than",
        "not",
        "be",
        "is",
        "per",
        "vs",
        "versus",
        "upon",
        "into",
        "between",
        "during",
        "within",
        "without",
        "through",
        "against",
        "about",
    }
)


def _is_noise_token(token: str) -> bool:
    """True for stopword, structural, digit, or collapsed-number residuals."""
    lowered = token.lower()
    return (
        lowered in _NOISE_RESIDUAL_TOKENS
        or token.isdigit()
        or lowered in ("num", "ord")
    )


def _residual_class(residuals: tuple[str, ...]) -> str:
    """Classify residuals as none, noise-only, or intent-bearing."""
    if not residuals:
        return "none"
    if all(_is_noise_token(token) for token in residuals):
        return "noise_only"
    return "intent_bearing"


#: Structural tags say where a thing sits, never what it is; they cannot carry identity.
_STRUCTURAL_MODIFIERS = frozenset({"M_CURRENT", "M_NONCURRENT"})


def _adequacy(
    head: str,
    modifiers: tuple[str, ...],
    residuals: tuple[str, ...],
    token_count: int,
) -> tuple[str, bool, float]:
    """Return (adequacy tier, has_identity, explained share) for one concept."""
    share = 1.0 - (len(residuals) / token_count if token_count else 0.0)
    intent = [t for t in residuals if not _is_noise_token(t)]
    # A name fully consumed by its head phrase carries identity in the head itself.
    has_identity = any(m not in _STRUCTURAL_MODIFIERS for m in modifiers) or not intent
    if head == "H_UNKNOWN":
        return "unmodelled", has_identity, share
    if not has_identity:
        return "identity_missing", has_identity, share
    if len(intent) >= 2 and share < 0.6:
        return "under_modded", has_identity, share
    if len(modifiers) >= 2 or share >= 0.6 or not intent:
        return "proper", has_identity, share
    return "under_modded", has_identity, share


def _statement_root_patterns() -> tuple[dict, ...]:
    """Load statement-root coordinate patterns from the taxonomy data."""
    path = resolve_xbrl_paths().default_statement_roots_path
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _root_slice(
    qname: str, lexicon: TokenLexicon, patterns: tuple[dict, ...]
) -> str | None:
    """Classify one presentation root by the declared coordinate patterns."""
    namespace = qname.split(":", 1)[0] if ":" in qname else ""
    tokens = set(tokenize_fact_concept(qname))
    head = decompose_concept_expression(qname, lexicon).atom.head
    for pattern in patterns:
        if pattern.get("namespace") and pattern["namespace"] != namespace:
            continue
        if pattern.get("head") and pattern["head"] != head:
            continue
        if not set(pattern.get("tokens_all", ())) <= tokens:
            continue
        return str(pattern["slice"])
    return None


def _placement_slices(
    arcs: pa.Table | None, lexicon: TokenLexicon
) -> dict[str, set[str]]:
    """Propagate statement slices from derived presentation roots down arcs."""
    if arcs is None or "parent_qname" not in arcs.column_names:
        return {}
    edges = list(
        zip(
            arcs.column("parent_qname").to_pylist(),
            arcs.column("child_qname").to_pylist(),
        )
    )
    children = {child for _, child in edges}
    patterns = _statement_root_patterns()
    slices: dict[str, set[str]] = {}
    seeded: set[str] = set()
    seen_roots: set[str] = set()
    for parent, _ in edges:
        if parent in children or parent in seen_roots:
            continue
        seen_roots.add(parent)
        slice_ = _root_slice(parent, lexicon, patterns)
        if slice_ is not None:
            slices[parent] = {slice_}
            seeded.add(parent)
    changed = True
    while changed:
        changed = False
        for parent, child in edges:
            source = slices.get(parent)
            if not source:
                continue
            target = slices.setdefault(child, set())
            if not source <= target:
                target |= source
                changed = True
    return {q: s for q, s in slices.items() if q not in seeded}


def _contains_phrase(stream: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """True when phrase occurs as an adjacent run inside stream."""
    n = len(phrase)
    return any(stream[i : i + n] == phrase for i in range(len(stream) - n + 1))


def _residual_collocations(
    decomposed: dict[str, tuple],
    firms_by_concept: dict[str, set[str]],
    firm_sics: dict[str, str],
) -> tuple[ResidualCollocation, ...]:
    """Mine recurrent residual bigrams/trigrams as phrase-merge candidates."""
    streams = {
        qname: tuple(token.lower() for token in residuals)
        for qname, (_atom, residuals) in decomposed.items()
        if len(residuals) >= 2
    }
    if not streams:
        return ()
    support = SupportCounter()
    for qname, stream in streams.items():
        for i in range(len(stream) - 1):
            for firm in firms_by_concept[qname]:
                support.observe(stream[i : i + 2], firm, firm_sics.get(firm, ""))

    def spread(phrase: tuple[str, ...]) -> tuple[int, int, str]:
        """Firm/SIC spread and first example among streams holding phrase."""
        firms: set[str] = set()
        example = ""
        for qname in sorted(streams):
            if _contains_phrase(streams[qname], phrase):
                firms |= firms_by_concept[qname]
                example = example or qname
        return len(firms), len({firm_sics[f] for f in firms if f in firm_sics}), example

    found: list[ResidualCollocation] = []
    mined = CollocationMiner(min_pmi=0.5, min_freq=3).mine_bigrams(
        list(streams.values()), support
    )
    for cand in mined:
        phrase = tuple(token.lower() for token in cand.phrase)
        _firms, _sics, example = spread(phrase)
        found.append(
            ResidualCollocation(
                phrase=phrase,
                frequency=cand.frequency,
                pmi=cand.pmi,
                firm_count=cand.firm_count,
                sic_count=cand.sic_count,
                structural=all(token in _STRUCTURAL_TOKENS for token in phrase),
                example_qname=example,
            )
        )
    extensions: Counter = Counter()
    for stream in streams.values():
        for i in range(len(stream) - 2):
            extensions[stream[i : i + 3]] += 1
    top_bigrams = {cand.phrase for cand in found}
    for phrase, freq in extensions.items():
        if freq < 3 or not any(
            phrase[:2] == bigram or phrase[1:] == bigram for bigram in top_bigrams
        ):
            continue
        firms, sics, example = spread(phrase)
        found.append(
            ResidualCollocation(
                phrase=phrase,
                frequency=freq,
                pmi=None,
                firm_count=firms,
                sic_count=sics,
                structural=all(token in _STRUCTURAL_TOKENS for token in phrase),
                example_qname=example,
            )
        )
    found.sort(key=lambda c: (-c.frequency, c.phrase))
    return tuple(found[:40])


def _statement_types() -> dict[str, str]:
    """Map each prime head id to its statement type from the taxonomy."""
    path = resolve_xbrl_paths().default_prime_heads_path
    records = json.loads(path.read_text(encoding="utf-8"))
    return {r["head_id"]: r.get("statement_type", "Unknown") for r in records}


def build_modelledness_report(
    bundles: Sequence[BundleFacts],
    lexicon: TokenLexicon,
    *,
    min_firms: int = 3,
    min_sics: int = 2,
    defaults: Iterable[DefaultCoordinate] = (),
) -> ModellednessReport:
    """Audit every distinct concept's modelled-ness across the bundles."""
    firms_by_concept: dict[str, set[str]] = defaultdict(set)
    sics_by_concept: dict[str, set[str]] = defaultdict(set)
    rows_by_concept: Counter = Counter()
    calc_degrees: Counter = Counter()
    pre_degrees: Counter = Counter()
    period_counts: dict[str, Counter] = defaultdict(Counter)
    placement_by_concept: dict[str, set[str]] = defaultdict(set)
    numeric_concepts: set[str] = set()
    has_numeric_column = False

    for bundle in bundles:
        qnames = bundle.facts.column("concept_qname").to_pylist()
        for qname in qnames:
            rows_by_concept[qname] += 1
            firms_by_concept[qname].add(bundle.firm)
            sics_by_concept[qname].add(bundle.sic_code)
        if "numeric_value" in bundle.facts.column_names:
            has_numeric_column = True
            for qname, value in zip(
                qnames, bundle.facts.column("numeric_value").to_pylist()
            ):
                if value is not None:
                    numeric_concepts.add(qname)
        if "period_type" in bundle.facts.column_names:
            for qname, period_type in zip(
                qnames, bundle.facts.column("period_type").to_pylist()
            ):
                period_counts[qname][period_type] += 1
        for qname, slices in _placement_slices(bundle.presentation_arcs, lexicon).items():
            placement_by_concept[qname] |= slices
        calc_degrees.update(_arc_degrees(bundle.calculation_arcs))
        pre_degrees.update(_arc_degrees(bundle.presentation_arcs))

    defaults = tuple(defaults)
    statement_types = _statement_types()
    atom_members: dict[str, list[str]] = defaultdict(list)
    decomposed: dict[str, tuple] = {}
    derived_by_concept: dict[str, str] = {}
    presumed_by_concept: dict[str, str] = {}
    for qname in rows_by_concept:
        expression = decompose_concept_expression(qname, lexicon)
        atom, residuals = expression.atom, expression.residuals
        decomposed[qname] = (atom, residuals)
        atom_members[str(atom)].append(qname)
        derived_by_concept[qname] = expression.derived_horizon or ""
        presumed = presumed_atom(atom, defaults)
        added = presumed.modifiers - atom.modifiers
        presumed_by_concept[qname] = next(iter(added)) if len(added) == 1 else ""

    records: list[ConceptModelledness] = []
    for qname in sorted(rows_by_concept):
        atom, residuals = decomposed[qname]
        namespace, _, local = qname.partition(":")
        token_count = len(split_camel_case(local))
        firm_count = len(firms_by_concept[qname])
        sic_count = len(sics_by_concept[qname])
        is_textblock = local.endswith("TextBlock") or (
            has_numeric_column and qname not in numeric_concepts
        )
        if namespace == "dei" and atom.head == "H_UNKNOWN":
            bucket = "excluded"
        elif namespace != "us-gaap":
            bucket = "extension"
        elif is_textblock:
            bucket = "textblock"
        elif (
            atom.head == "H_UNKNOWN"
            or (token_count >= 5 and len(atom.modifiers) <= 1)
            or (
                len(residuals) >= 2
                and firm_count >= min_firms
                and sic_count >= min_sics
            )
        ):
            bucket = "candidate"
        else:
            bucket = "modelled"
        adequacy, has_identity, share = _adequacy(
            atom.head, tuple(sorted(atom.modifiers)), tuple(residuals), token_count
        )
        records.append(
            ConceptModelledness(
                qname=qname,
                namespace=namespace,
                token_count=token_count,
                residual_tokens=tuple(residuals),
                head=atom.head,
                modifiers=tuple(sorted(atom.modifiers)),
                atom=str(atom),
                collision_group_size=len(atom_members[str(atom)]),
                firm_count=firm_count,
                sic_count=sic_count,
                fact_rows=rows_by_concept[qname],
                calculation_degree=calc_degrees[qname],
                presentation_degree=pre_degrees[qname],
                bucket=bucket,
                statement_slice=statement_types.get(atom.head, "Unknown"),
                residual_class=_residual_class(tuple(residuals)),
                explained_share=share,
                adequacy=adequacy,
                has_identity=has_identity,
                derived_horizon=derived_by_concept[qname],
                presumed_modifier=presumed_by_concept[qname],
            )
        )

    candidates = tuple(
        sorted(
            (r for r in records if r.bucket == "candidate"),
            key=lambda r: (
                -r.firm_count,
                -r.sic_count,
                -math.log10(r.fact_rows + 1),
                -(len(r.residual_tokens) / r.token_count if r.token_count else 0.0),
                r.qname,
            ),
        )
    )
    collision_groups = tuple(
        (atom, len(members), tuple(sorted(members)[:25]))
        for atom, members in sorted(
            atom_members.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )
        if len(members) >= 5
    )
    frame_conflicts: list[FrameConflict] = []
    for record in records:
        expected = {"BalanceSheet": "instant", "IncomeStatement": "duration"}.get(
            record.statement_slice
        )
        if expected is None or record.bucket == "textblock":
            continue
        counts = period_counts.get(record.qname, Counter())
        instant, duration = counts.get("instant", 0), counts.get("duration", 0)
        total = instant + duration
        if total < 5:
            continue
        opposed = duration if expected == "instant" else instant
        if opposed / total < 0.9:
            continue
        frame_conflicts.append(
            FrameConflict(
                qname=record.qname,
                head=record.head,
                head_slice=record.statement_slice,
                period_profile="duration" if expected == "instant" else "instant",
                instant_facts=instant,
                duration_facts=duration,
                placement_slices=tuple(
                    sorted(placement_by_concept.get(record.qname, set()))
                ),
                firm_count=record.firm_count,
            )
        )
    frame_conflicts.sort(
        key=lambda c: (-c.firm_count, -(c.instant_facts + c.duration_facts), c.qname)
    )
    by_atom: dict[str, list[ConceptModelledness]] = defaultdict(list)
    for record in records:
        if record.bucket != "textblock":
            by_atom[record.atom].append(record)
    identity_collisions = tuple(
        IdentityCollision(
            atom=atom,
            concept_count=len(members),
            members=tuple(
                (m.qname, m.residual_tokens)
                for m in sorted(members, key=lambda m: m.qname)[:25]
            ),
        )
        for atom, members in sorted(
            by_atom.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )
        if len(members) >= 5
    )
    by_signature: dict[tuple, list[ConceptModelledness]] = defaultdict(list)
    for record in records:
        if record.bucket in ("textblock", "excluded"):
            continue
        intent = tuple(
            sorted(
                {t.lower() for t in record.residual_tokens if not _is_noise_token(t)}
            )
        )
        by_signature[(record.head, record.modifiers, intent)].append(record)
    pattern_groups: list[PatternGroup] = []
    for (head, modifiers, intent), members in by_signature.items():
        firms = sorted({f for m in members for f in firms_by_concept[m.qname]})
        if len(firms) < 2:
            continue
        pattern_groups.append(
            PatternGroup(
                head=head,
                modifiers=modifiers,
                residual_signature=intent,
                firms=tuple(firms),
                sics=tuple(
                    sorted({s for m in members for s in sics_by_concept[m.qname]})
                ),
                concept_count=len(members),
                fact_rows=sum(m.fact_rows for m in members),
                examples=tuple(sorted(m.qname for m in members)[:10]),
            )
        )
    pattern_groups.sort(key=lambda g: (-len(g.firms), -g.fact_rows, g.head))
    return ModellednessReport(
        total_concepts=len(records),
        total_fact_rows=sum(rows_by_concept.values()),
        unknown_head_concepts=sum(1 for r in records if r.head == "H_UNKNOWN"),
        us_gaap_unknown_non_textblock=sum(
            1
            for r in records
            if r.namespace == "us-gaap"
            and r.bucket != "textblock"
            and r.head == "H_UNKNOWN"
        ),
        long_and_bare_us_gaap=sum(
            1
            for r in records
            if r.namespace == "us-gaap"
            and r.bucket != "textblock"
            and r.token_count >= 5
            and len(r.modifiers) <= 1
        ),
        bucket_counts=tuple(sorted(Counter(r.bucket for r in records).items())),
        candidate_slice_counts=tuple(
            sorted(Counter(r.statement_slice for r in candidates).items())
        ),
        collision_groups=collision_groups,
        candidates=candidates,
        concepts=tuple(records),
        residual_collocations=_residual_collocations(
            decomposed,
            firms_by_concept,
            {bundle.firm: str(bundle.sic_code) for bundle in bundles},
        ),
        us_gaap_unknown_noise_only=sum(
            1
            for r in records
            if r.namespace == "us-gaap"
            and r.bucket != "textblock"
            and r.head == "H_UNKNOWN"
            and r.residual_class == "noise_only"
        ),
        long_and_bare_noise_only=sum(
            1
            for r in records
            if r.namespace == "us-gaap"
            and r.bucket != "textblock"
            and r.token_count >= 5
            and len(r.modifiers) <= 1
            and r.residual_class == "noise_only"
        ),
        residual_noise_token_total=sum(
            1 for r in records for token in r.residual_tokens if _is_noise_token(token)
        ),
        residual_intent_token_total=sum(
            1
            for r in records
            for token in r.residual_tokens
            if not _is_noise_token(token)
        ),
        frame_conflicts=tuple(frame_conflicts[:120]),
        adequacy_counts=tuple(sorted(Counter(r.adequacy for r in records).items())),
        identity_collisions=identity_collisions,
        pattern_groups=tuple(pattern_groups[:120]),
    )
