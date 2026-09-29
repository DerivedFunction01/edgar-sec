# `edgar_sec/domain/taxonomy/` — Statutory name vocabulary for jurisdictions, legal forms, and company families

The words that are grammar rather than identity. A state code after a slash, an
`INC` at the end of a name, an abbreviation that is only safe to expand next to
a particular neighbour: all of it is declared here so name comparison and
clustering mean the same thing everywhere.

## Purpose

`edgar_sec/domain/taxonomy/` owns the reference tables and pure normalizers used
to decide whether two registrant names belong to the same family: US state and
territory codes, legal-form suffixes, function words, security-depository
abbreviations, plural forms, Roman numerals, and the tuning constants for family
resolution. It is not the family clustering algorithm
(`engine/company_family/normalizer.py` and `clustering.py`), not the feature
snapshot that consumes the result, and not the financial *table* taxonomy that
shares its name in v1.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `jurisdictions.py` | `STATE_POSTAL_CODES`, `STATE_NAMES`, `JURISDICTION_RE`, `strip_jurisdiction()`, `clean_entity_name()` |
| `legal_forms.py` | `LEGAL_FORMS`, `NAME_STOPWORDS`, `entity_name_tokens()` |
| `family_vocab.py` | `ABBR_MAP`, `CONTEXT_RULES`, `PLURAL_MAP`, `ROMAN`, `PLACEHOLDER`, `STATE_CODES`, `SEED`, and the five tuning constants |

## Contracts

**Guarantees this package makes.**

- Every table is immutable. `frozenset` for membership and neighbour sets,
  `MappingProxyType` for mappings. The module docstring gives the reason: a
  mutable table would let one caller corrupt the vocabulary for the whole
  process, and the clustering result would then depend on call order rather than
  on the input. `AGENTS.md`'s contract for this package is a data-only module,
  and immutability is what makes that data trustworthy.
- The jurisdiction suffix is removed only when it is one. `JURISDICTION_RE`
  matches a slash-delimited suffix closed by a second slash or by end of string,
  against a fixed code list. A slash inside a name that is not followed by a
  statutory code survives untouched (`jurisdictions.py:4-7`).
- The compiled pattern is byte-identical on every run. The alternation is built
  in `sorted(STATE_POSTAL_CODES)` order at import time
  (`jurisdictions.py:134-136`), so the pattern is reproducible across processes
  and machines.
- Legal-form stripping is symmetric. `entity_name_tokens()` calls
  `strip_jurisdiction()` first, so `ACME HOLDINGS INC/CA` and `ACME HOLDINGS LLC`
  both tokenise to `['acme']` — `inc`, `llc`, and `holdings` are all in
  `LEGAL_FORMS`, so the form, the jurisdiction, the function words, and the
  single characters are all removed before comparison. Single characters are
  dropped because they are almost always formatting artifacts
  (`legal_forms.py:90-92`).
- The dependency between the two modules is one-way. `legal_forms.py` imports
  `strip_jurisdiction` from `jurisdictions.py`; nothing imports the reverse. The
  split is deliberate and recorded: `clean_entity_name` lives with jurisdictions
  (it is jurisdiction stripping plus whitespace normalisation) and
  `entity_name_tokens` with legal forms (it filters on both legal forms and
  stopwords) — `roadmap/refactor_v2/phase_2.md:789-792`.
- Ambiguous abbreviations are not expanded blindly. `ABBR_MAP` holds only
  unambiguous ones; the ambiguous set lives in `CONTEXT_RULES` as
  `token -> (expansion, allowed previous, allowed next)`, because expanding them
  unconditionally would corrupt unrelated names. Both neighbours are checked:
  `tr` is `trust` only after a security type, `series`, and so on
  (`family_vocab.py:69-72`, `:93-109`).
- An empty neighbour set means "no constraint on that side", not "never".
  The type is `tuple[str, frozenset[str], frozenset[str]]` and the comment at
  `family_vocab.py:70-71` is explicit.
- Family ids are reproducible by construction. `SEED = "phase-02-company-family"`
  is fixed so ids are stable across runs and machines; changing it deliberately
  invalidates every derived family id (`family_vocab.py:19-21`).
- A series letter never splits a family. `PLACEHOLDER = {"D", "S", "R"}` is
  excluded from family keys, and `ROMAN` collapses `SERIES IV` and `SERIES D` to
  the same token class (`family_vocab.py:158-186`).
- `STATE_CODES` is the lower-cased form of `STATE_POSTAL_CODES`, sorted at
  import, for case-insensitive matching against already-normalized names
  (`family_vocab.py:189`). It is a `tuple`, not a `frozenset`, because order is
  what a caller scanning names needs.

**Obligations callers place on this package.**

- Treat these tables as read-only input to an algorithm that lives above. The
  family algorithm is `engine/company_family/`; the five tuning constants
  (`HEAD_TOKENS = 3`, `MIN_ALIAS_CHARS = 6`, `MIN_CLUSTER_ATTACH = 2`,
  `MAX_PARENT_TOKENS = 4`, `STRUCTURAL_THRESHOLD = 1`) are the only knobs in
  family resolution, and they are here so the algorithm module holds logic and
  this module holds data.
- Do not widen `ABBR_MAP` with an ambiguous token. Add it to `CONTEXT_RULES` with
  its neighbour constraints instead.
- `strip_jurisdiction()` replaces the matched suffix with a single space and
  strips; it does not collapse interior whitespace. `clean_entity_name()` is the
  one that normalises whitespace, and it is what
  `engine/forms/cover/extractors.py:12` imports.

## Public surface

- `STATE_POSTAL_CODES` — `frozenset` of 54 entries: the 50 states plus `DC` and
  the three territories that appear in EDGAR incorporation fields (`PR`, `VI`,
  `GU`); `jurisdictions.py:16`.
- `STATE_NAMES` — `frozenset` of 54 lowercase full names, including
  `district of columbia`, `puerto rico`, `virgin islands`, and `guam`;
  `jurisdictions.py:75`.
- `JURISDICTION_RE` — the compiled suffix pattern, `re.IGNORECASE`;
  `jurisdictions.py:140`.
- `strip_jurisdiction(raw)` — remove the slash-delimited jurisdiction suffix;
  `jurisdictions.py:146`.
- `clean_entity_name(raw)` — `strip_jurisdiction()` plus whitespace collapse;
  `jurisdictions.py:151`.
- `LEGAL_FORMS` — `frozenset` of 41 entity-type words, US and non-US (EDGAR
  carries foreign private issuers), plus holding/group/trust/fund and bancorp
  words; `legal_forms.py:18`.
- `NAME_STOPWORDS` — `frozenset` of 15 function words, including `&` because
  EDGAR names use it in place of "and"; `legal_forms.py:66`.
- `entity_name_tokens(name)` — lower-cased `[a-z0-9]+` tokens with legal forms,
  stopwords, and single characters removed; `legal_forms.py:89`.
- `SEED` — `"phase-02-company-family"`; `family_vocab.py:21`.
- `HEAD_TOKENS` (3), `MIN_ALIAS_CHARS` (6), `MIN_CLUSTER_ATTACH` (2),
  `MAX_PARENT_TOKENS` (4), `STRUCTURAL_THRESHOLD` (1) — `family_vocab.py:24-32`.
- `ABBR_MAP` — 27 unambiguous abbreviation expansions
  (`MappingProxyType[str, str]`); `family_vocab.py:37`.
- `CONTEXT_RULES` — 10 context-gated expansions (`as`, `bk`, `com`, `comm`,
  `ct`, `ps`, `se`, `sr`, `srs`, `tr`) as
  `MappingProxyType[str, tuple[str, frozenset[str], frozenset[str]]]`;
  `family_vocab.py:73`.
- `PLURAL_MAP` — 17 singular forms, applied after abbreviation expansion;
  `family_vocab.py:136`.
- `ROMAN` — `frozenset` of 20 Roman numerals, `I` through `XX`;
  `family_vocab.py:159`.
- `PLACEHOLDER` — `frozenset` of `D`, `S`, `R`; `family_vocab.py:186`.
- `STATE_CODES` — sorted, lower-cased 54-tuple; `family_vocab.py:189`.

## Tests

```text
tests/domain/taxonomy/test_taxonomy.py    22 test functions, 219 lines
```

## Deliberate gaps

- **This package is not the v1 `defs/taxonomy/`, and the shared name is
  recorded as unresolved.** v1's `defs/taxonomy/` was the financial *table*
  classification engine — `TableFamilySpec`, `EvidenceTier`, `ShapeConstraint`,
  `RepairPolicy`, a multi-zone BoW classifier, per-statement component specs, and
  a probe CLI (see `.v1/defs/taxonomy/README.md`). v2's `domain/taxonomy/`
  sources instead from v1's `defs/entities/lexicon.py`, as
  `roadmap/refactor_v2/phase_2.md:219-220` records. The table-classification
  subsystem has no v2 home in this layer; `roadmap/refactor_v2/v2_refactor_roadmap.md:1253-1256`
  states that the collision is unacknowledged outside that one milestone row.
  Do not read this package as the successor to v1's table taxonomy.
- **Form-family classification is not here either.** The roadmap is explicit
  that `10-K/A` → `10-K` is a *selection* concern, not a taxonomy one, and that
  an earlier matrix describing the package as holding "SEC form classifications"
  was wrong on the merits. The vocabulary in this package is company-*name*
  vocabulary; the form alias table is `edgar_sec/domain/forms/families.py`.
  See `roadmap/refactor_v2/v2_refactor_roadmap.md:243-247`.
- **`build_alternation` is deliberately not used in `jurisdictions.py`.** The
  state alternation is a one-line `"|".join(re.escape(code) ...)` over a sorted
  set. `roadmap/refactor_v2/phase_2.md:783-788` records the reason: `build_alternation`
  was a v1-only helper with no v2 equivalent, and introducing a shared module for
  a single expression would cost more than it saved. The inline join also passes
  the `regex-alternations` scanner because that rule matches a *literal*
  alternation in source text, and this one is computed.
- **`tests/domain/taxonomy/test_taxonomy.py` covers all three modules in one
  file.** That departs from `AGENTS.md` §6.3 ("one test file per source module"),
  which would imply `test_jurisdictions.py`, `test_legal_forms.py`, and
  `test_family_vocab.py`. The coverage is real — 22 test functions across all
  three modules — but the file layout is a deviation, not the intended shape.
- **`STATE_POSTAL_CODES` and `forms/vocabulary.py::_US_STATES` are two state
  lists with different membership.** This package's 54 codes include `PR`, `VI`,
  and `GU`; the forms vocabulary's private 102-entry set includes full state
  *names* and none of those three territories. The 51 shared codes are identical.
  Neither module records why the second list exists, and the natural resolution
  is for `is_state_value()` to consult this package. Until that is decided, a
  Puerto Rico incorporation value is accepted by `strip_jurisdiction()` and
  rejected by `is_state_value()`.
- **No clustering, no resolution, and no name comparison lives here.** This
  package supplies tables and three pure functions; `engine/company_family/`
  supplies the normalizer and the corpus-dependent clustering, and
  `engine/selection/features.py:45` imports `STATE_POSTAL_CODES` for its own
  feature dimension.
- **No legal-form table for jurisdictions outside the US.** `STATE_POSTAL_CODES`
  is the statutory US list plus three territories. Foreign private issuers on
  EDGAR carry non-US forms in `LEGAL_FORMS` (`gmbh`, `kgaa`, `sa`, `bv`, `srl`,
  `lda`, `spa`, …) but their jurisdictions are not modelled, so
  `strip_jurisdiction()` will not remove a non-US slash suffix.
