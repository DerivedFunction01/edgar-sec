"""Mining fact concept token sequences and n-grams across grounded fixtures."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path

import pyarrow as pa

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths


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
