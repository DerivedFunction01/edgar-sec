# `defs/text/` — Text Normalization, Repair, and Lexical Evidence

Domain-neutral text processing primitives and engines. Modules here provide
leaf character/token syntax, layout structure classification, lexical Bag-of-Words
(BoW) matching, representation-neutral line and whitespace healing, string-first
HTML parsing, and conservative ASCII reflow.

```text
defs/text/
  syntax/              # Leaf character, glyph, date, and token syntax (zero internal deps)
    unicode.py         # Unicode whitespace, zero-width spaces, character normalization
    tokens.py          # Bullet markers, roman numerals, ordered list markers
    dates.py           # Strict date parsing, regex patterns, components, 2-digit century pivot
    checkmarks.py      # Checkbox marks, glyph categories, ASCII fallback brackets
    signatures.py      # Conformed signature (/s/) markers, title detection, uppercase repair
    grammar.py         # English stopwords, articles, pronouns, transitions, verbal participles
  structure/           # Layout patterns, line/paragraph grouping, text counters
    patterns.py        # Column gaps, dot leaders, terminal sentence punctuation, separator lines
    logical_units.py   # LogicalUnit classification (paragraph, header, list, table, etc.)
    counts.py          # Bounded line and word counting utilities
  bow/                 # Token-level lexical evidence engine
    engine.py          # Compile and evaluate LexicalEvidencePack, scoring, tiered classification
    types.py           # Immutable token models, compiled tier dataclasses, MatchPayload
    match.py           # Windowed matching, hit detection, distinct token counters
    automaton.py       # High-throughput Aho-Corasick multi-pattern automaton
  healing/             # Representation-neutral line and whitespace repair
    lines.py           # Soft-wrapped line joining, Yes/No checkbox block normalization
    compounds.py       # Cartesian compound expansion, variant generation
    whitespace.py      # Bullet split normalization, paragraph blank-line compaction
  html/                # String-first HTML normalizer and structure cleaner
    pipeline.py        # String-first HTML pipeline, tag canonicalization, table protection
    tree.py            # Fast DOM tree parser retained for table and context consumers
    decompose.py       # Tag decomposition into standard text, lists, headings
    cleaner.py         # iXBRL strip, font attribute sanitization, metadata removal
  reflow/              # Conservative ASCII reflow engine and table preservation
    engine.py          # Block segmentation, decision dispatch (UNWRAP / PRESERVE / TAG_AND_PRESERVE)
    classifier.py      # Heuristic and machine feature classification
    context.py         # BlockContext and surrounding evidence tracking
    registry.py        # Feature registry and feature extraction pipelines
  __init__.py          # Public re-export facade maintaining backward compatibility
```

## Architectural Contracts

1. **Leaf Invariant for `defs.text.syntax`**:
   `defs.text.syntax` is strictly a leaf package. It never imports from `defs.tables`,
   `defs.sec_forms`, `defs.taxonomy`, or any sibling subpackages within `defs.text`.
   It provides pure tokenization and syntax definitions.
2. **Circular Dependency Prevention**:
   External modules such as `defs.tables` and `defs.sec_forms` consume leaf primitives
   directly from `defs.text.syntax` or `defs.text.structure`.
   `defs.text.reflow` resolves table regions via lazy imports to prevent cycles with
   `defs.tables`.
3. **Domain Isolation**:
   No form-specific (e.g. Form 10-K or 10-Q) literals or vocabulary exist in `defs/text/`.
   Regulatory form schemas belong in `defs/sec_forms/`, and financial table taxonomy
   definitions belong in `defs/taxonomy/`.
