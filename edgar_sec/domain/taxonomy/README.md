# `edgar_sec/domain/taxonomy/` — Statutory name vocabulary

The words that are grammar rather than identity: a state code after a slash, an `INC` at
the end of a name, an abbreviation that is only safe to expand next to a particular
neighbour.

## Purpose

Owns the reference tables and pure normalizers used to decide whether two registrant names
belong to the same family: US state and territory codes, legal-form suffixes, function
words, security-depository abbreviations, plural forms, Roman numerals, and the tuning
constants for family resolution. Not the clustering algorithm
(`engine/company_family/`), not the feature snapshot that consumes the result, and not the
financial *table* taxonomy that shares this package's name in v1.

## Layout

| Subpackage / Module | Responsibility |
| :--- | :--- |
| `jurisdictions.py` | `STATE_POSTAL_CODES`, `STATE_NAMES`, `JURISDICTION_RE`, `strip_jurisdiction()`, `clean_entity_name()` |
| `legal_forms.py` | `LEGAL_FORMS`, `NAME_STOPWORDS`, `entity_name_tokens()` |
| `family_vocab.py` | `ABBR_MAP`, `CONTEXT_RULES`, `PLURAL_MAP`, `ROMAN`, `PLACEHOLDER`, `STATE_CODES`, `SEED`, and the five tuning constants |
| `components/cover.py` | Cover-page table family specs and term sets (`COVER_LAYOUT_SPEC`, `CHECKBOX_GRID_SPEC`, `REGISTRATION_TABLE_SPEC`, registrant/EIN/ZIP/phone term sets) |
| `statements/` | Primary financial statement line items, structural tail regexes, and line predicates — see `statements/README.md` |
| `schedules/` | Footnote note schedules and statutory exhibit index concepts — see `schedules/README.md` |
| `tables/` | Declarative table family specifications and geometric constraints — see `tables/README.md` |

## Contracts

- Every table is immutable: `frozenset` for membership and neighbour sets,
  `MappingProxyType` for mappings. A mutable table would let one caller corrupt the
  vocabulary for the whole process, making the clustering result depend on call order
  rather than on the input.
- The compiled jurisdiction pattern is byte-identical on every run: the alternation is built
  in `sorted(STATE_POSTAL_CODES)` order at import time.
- A jurisdiction suffix is removed only when it is a statutory code. `JURISDICTION_RE`
  matches a slash-delimited suffix closed by a second slash or by end of string, so an
  unrelated slash inside a name survives untouched.
- Legal-form stripping is symmetric. `entity_name_tokens()` calls `strip_jurisdiction()`
  first, so `ACME HOLDINGS INC/CA` and `ACME HOLDINGS LLC` both tokenise to `['acme']`:
  the form, the jurisdiction, the function words, and single characters (almost always
  formatting artifacts) are all removed before comparison.
- The dependency between the two modules is one-way. `legal_forms.py` imports
  `strip_jurisdiction` from `jurisdictions.py`; nothing imports the reverse. The split is
  recorded in `roadmap/refactor_v2/phase_2.md`: `clean_entity_name` lives with
  jurisdictions, `entity_name_tokens` with legal forms.
- Ambiguous abbreviations are not expanded blindly. `ABBR_MAP` holds only unambiguous
  expansions; the ambiguous set lives in `CONTEXT_RULES` as
  `token -> (expansion, allowed previous, allowed next)`, because expanding them
  unconditionally would corrupt unrelated names. Both neighbours are checked — `tr` is
  `trust` only after a security type or `series`.
- An empty neighbour set means "no constraint on that side", not "never".
- Family ids are reproducible by construction: `SEED` is fixed, so changing it deliberately
  invalidates every derived family id.
- A series letter never splits a family. `PLACEHOLDER = {"D", "S", "R"}` is excluded from
  family keys, and `ROMAN` collapses `SERIES IV` and `SERIES D` to the same token class.
- `STATE_CODES` is the sorted, lower-cased form of `STATE_POSTAL_CODES`, for case-insensitive
  matching against already-normalised names. It is a `tuple`, not a `frozenset`, because a
  caller scanning names needs the order.

**Obligations on callers.**

- Treat these tables as read-only input to an algorithm that lives above. The five tuning
  constants (`HEAD_TOKENS`, `MIN_ALIAS_CHARS`, `MIN_CLUSTER_ATTACH`, `MAX_PARENT_TOKENS`,
  `STRUCTURAL_THRESHOLD`) are the only knobs in family resolution, and they are here so the
  algorithm module holds logic and this module holds data.
- Do not widen `ABBR_MAP` with an ambiguous token. Add it to `CONTEXT_RULES` with its
  neighbour constraints instead.
- `strip_jurisdiction()` replaces the matched suffix with a single space and strips; it does
  not collapse interior whitespace. `clean_entity_name()` is the one that normalises
  whitespace.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `STATE_POSTAL_CODES` (54: the 50 states, `DC`, and `PR`/`VI`/`GU`), `STATE_NAMES` (54 lowercase full names), `JURISDICTION_RE`, `strip_jurisdiction(raw)`, `clean_entity_name(raw)` | `jurisdictions.py` |
| `LEGAL_FORMS` (41 entity-type words, US and non-US, plus holding/group/trust/fund/bancorp words), `NAME_STOPWORDS` (15 function words, including `&`), `entity_name_tokens(name)` | `legal_forms.py` |
| `SEED`, `HEAD_TOKENS` (3), `MIN_ALIAS_CHARS` (6), `MIN_CLUSTER_ATTACH` (2), `MAX_PARENT_TOKENS` (4), `STRUCTURAL_THRESHOLD` (1) | `family_vocab.py` |
| `ABBR_MAP` (27 unambiguous expansions), `CONTEXT_RULES` (10 context-gated: `as`, `bk`, `com`, `comm`, `ct`, `ps`, `se`, `sr`, `srs`, `tr`), `PLURAL_MAP` (17 singular forms) | `family_vocab.py` |
| `ROMAN` (20 numerals, `I`–`XX`), `PLACEHOLDER`, `STATE_CODES` (54-tuple) | `family_vocab.py` |
| Cover specs and term sets (`COVER_LAYOUT_SPEC`, `CHECKBOX_GRID_SPEC`, `REGISTRATION_TABLE_SPEC`, registrant/EIN/ZIP/phone/state terms, `ALL_ENTITY_COORDINATE_FIELDS`) | `components/cover.py` |

No command surface.

## Tests

```text
tests/domain/taxonomy/test_taxonomy.py
```

## Deliberate gaps

- **All three source modules share one test file.** `test_taxonomy.py` departs from
  `AGENTS.md` §6.3 ("one test file per source module"), which would imply
  `test_jurisdictions.py`, `test_legal_forms.py`, and `test_family_vocab.py`. The coverage
  is real — 22 test functions across all three — but the file layout is a deviation.
- **`components/` is a namespace directory with no `__init__.py`.** It works as an implicit
  namespace package, so it escapes the "every test directory is a package" convention that
  `tests/` follows and would break under a stricter packaging tool.
- **This package is not v1's `defs/taxonomy/`, and the name collision is unresolved.** v1's
  `defs/taxonomy/` was the financial *table* classification engine (`TableFamilySpec`,
  `EvidenceTier`, `ShapeConstraint`, `RepairPolicy`, a multi-zone BoW classifier, per-statement
  component specs, and a probe CLI — see `.v1/defs/taxonomy/README.md`). v2's
  `domain/taxonomy/` sources instead from v1's `defs/entities/lexicon.py`, as
  `roadmap/refactor_v2/phase_2.md:224` records. `roadmap/refactor_v2/v2_refactor_roadmap.md:1256`
  states the collision is written down only in that one milestone row. Do not read this
  package as the successor to v1's table taxonomy.
- **Form-family classification is not here.** The roadmap is explicit that `10-K/A` → `10-K`
  is a *selection* concern, and that an earlier matrix describing this package as holding
  "SEC form classifications" was wrong on the merits. The vocabulary here is company-*name*
  vocabulary; the form alias table is `edgar_sec/domain/forms/common/aliases.py`
  (`roadmap/refactor_v2/v2_refactor_roadmap.md:243-249`).
- **`build_alternation` is deliberately not used in `jurisdictions.py`.** The state
  alternation is a one-line `"|".join(re.escape(code) ...)` over a sorted set;
  `roadmap/refactor_v2/phase_2.md:788-792` records that `build_alternation` was a v1-only
  helper with no v2 equivalent, and introducing a shared module for a single expression
  would cost more than it saved. The inline join also passes the `regex-alternations`
  scanner, which matches a *literal* alternation in source text.
- **`clean_entity_name()` has no production consumer.** Only `tests/domain/taxonomy/` calls
  it; `strip_jurisdiction()`, `LEGAL_FORMS`, `JURISDICTION_RE`, `STATE_POSTAL_CODES`, and
  `family_vocab` are the tables and functions `engine/company_family/` and
  `engine/selection/features.py` actually import.
- **`entity_name_tokens()` also has no production consumer.** The engine tokenises through
  its own `strip_legal_forms()` over `LEGAL_FORMS`, so this function is the reference
  semantics rather than the live path.
- **No legal-form table for jurisdictions outside the US.** `STATE_POSTAL_CODES` is the
  statutory US list plus three territories. Foreign private issuers carry non-US forms in
  `LEGAL_FORMS` (`gmbh`, `kgaa`, `sa`, `bv`, `srl`, `lda`, `spa`, …) but their jurisdictions
  are not modelled, so `strip_jurisdiction()` will not remove a non-US slash suffix.
- **The state list here is the canonical one.** `domain/forms/common/vocabulary.py`
  derives its `_US_STATES` from `STATE_POSTAL_CODES` and `STATE_NAMES` rather than keeping a
  second list, so `is_state_value()` accepts `PR`, `VI`, and `GU` today.