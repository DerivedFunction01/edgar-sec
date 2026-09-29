# `edgar_sec/domain/forms/` — Cover and form vocabulary, checkmark tokens, and evaluator contracts

The vocabulary of an SEC form: what its cover page says, what a checked box
looks like, which form strings are the same form, what body prose sounds like,
and what a form evaluator may decide. All of it is data; none of it reads a
document.

## Purpose

`edgar_sec/domain/forms/` owns every table and pattern that the cover-page and
form-evaluation engine needs to agree on: label aliases, filer-status constants,
checkmark token boundaries, the statutory checkbox constraint set, body-evidence
tiers, the form-family alias registry, and the two evaluator decision types. It
is not the extractor, the checkmark solver, the boundary detector, or the
evaluators — those live in `engine/forms/`, which imports downward from here.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `vocabulary.py` | `COVER_LABELS` and its eight derived field-label regexes, filer-status constants, `FILER_CATEGORY_PATTERNS`, `CHECKBOX_KEYWORDS`, `CHECKBOX_GRID_RE`, value patterns, and `is_state_value()` |
| `checkmarks.py` | Canonical `[X]`/`[ ]` tokens, bracket pairs, checked/unchecked symbol and HTML-entity sets, `FONT_GLYPH_MAPPINGS`, and the `CHECKMARK_MARK_RE` scan pattern |
| `schemas.py` | `CheckboxConstraint`, `CoverCheckboxSchema`, the seven `STATUTORY_CHECKBOX_CONSTRAINTS`, and the two annual/quarterly schema instances |
| `families.py` | `FORM_FAMILY_ALIASES`, `FORM_FAMILY_SUFFIXES`, and the `form_family` / `resolve_alias` / `normalize_form` / `aliases_for_family` lookup API |
| `body_evidence.py` | Strong, soft, weak, verb, forward-looking, cover-exclusion, and semantic-heading tiers used to end the cover region |
| `decisions.py` | `DecisionAction` and `EvaluatorDecision` |

## Contracts

**Guarantees this package makes.**

- One alias table per concept. `families.py` maps raw form strings to canonical
  families through a single `FORM_FAMILY_ALIASES` registry covering `10-K`,
  `10-Q`, `8-K`, `20-F`, and `6-K`, with amendment and submission suffixes
  included explicitly. `resolve_alias()` returns `None` for an unrecognised form
  rather than guessing (`families.py:94-105`).
- Suffix stripping is ordered. `FORM_FAMILY_SUFFIXES` is applied with
  `removesuffix`, each entry at most once, so `"10-K/A-POS"` needs `-POS`
  removed before `/A` (`families.py:56-67`, mirrored in the identical comment on
  `engine/selection/features.py:56-57`). A form that is *entirely* suffixes
  (`"/A"`) collapses to the empty string and the original is returned rather
  than an empty dimension value (`families.py:81-91`).
- Regexes are built with the DSL, not by hand. The eight field-label patterns
  and `_phrase_pattern()` all route through
  `build_alternation(..., auto_escape=True, flexible_whitespace=True)` from
  `foundation.regex.builder`, which is what keeps them longest-first and
  safely anchored. The `regex-alternations` scanner's exemption list is only
  `foundation/regex/` and `foundation/text/`, so this package is scanned, not
  exempt.
- Filer-status matching is ordered so "large accelerated filer" is not also read
  as "accelerated filer": `FILER_CATEGORY_PATTERNS` lists
  `LARGE_ACCELERATED_FILER` and `NON_ACCELERATED_FILER` before the bare
  `Accelerated filer` entry, which additionally carries a `(?<!large\s)` negative
  lookbehind (`vocabulary.py:133-142`).
- Checkbox vocabulary is interpreted, not guessed. `CANONICAL_CHECKED` and
  `CANONICAL_UNCHECKED` are the only two normalised outputs, and
  `CheckmarkScope` is the policy controlling which source marks may be
  interpreted at all (`checkmarks.py:29-34`).
- Statutory constraints are declarative. Each `CheckboxConstraint` names a
  relation (`not_both`, `implies`), its left and right states, a default penalty
  of 300, and a description. `shell_404b_exemption` sets `right_state="unchecked"`
  to express the exemption direction without a new relation type.
- Body evidence is tiered by decision weight. `body_evidence.py` documents that
  a strong phrase alone clears the boundary, a soft phrase alone never does
  (covers quote forward-looking boilerplate), and two distinct terms are the
  minimum for the unigram and weak tiers.

**Obligations callers place on this package.**

- Do not compile a checkbox token here. Use `RE_RAW_CHECKED` / `RE_RAW_UNCHECKED`
  for raw classification and `CHECKMARK_MARK_RE` for a broad scan; the token
  *sets* are the vocabulary, and the regexes are the sanctioned accessors.
- Treat `FILER_STATUS_TERMS` as scoping vocabulary, not as a matched set. Its
  comment names the consumer: "Used by the cover rewrite engine to scope mark
  normalization" (`schemas.py:121-122`).
- Consume `DecisionAction` as the closed set of three. `PROCEED`,
  `REFETCH_SUB_DOC`, and `SKIP_HARD_STUB` are what exist
  (`decisions.py:10-16`); a fourth member is a schema change, not an addition.
- Keep per-form vocabulary out of this package. The module docstring for
  `families.py` states the rule: no consumer owns a private alias list.

## Public surface

Form family — `edgar_sec/domain/forms/families.py`:

- `FORM_FAMILY_ALIASES` — `dict[str, tuple[str, ...]]` of 5 families to their
  aliases, including `10-K405`, `10KSB40`, `10-KT`, `10-QSB`, `8-K12B`,
  `8-K15D5`, `20FR12B`, `20FR12G3`.
- `FORM_FAMILY_SUFFIXES` — `("_A", "_W", "_POS", "-POS", "MEF", "-W", "/A")`.
- `form_family(form)` — suffix-collapse only; returns the base string.
- `resolve_alias(form)` — full lookup; `None` when unknown.
- `normalize_form(form)` — alias for `resolve_alias`.
- `aliases_for_family(family)` — the canonical alias tuple, `()` when unknown.

Checkbox schemas — `edgar_sec/domain/forms/schemas.py`:

- `CheckboxConstraint` — frozen, slots: `name`, `relation`, `left`, `right`,
  `left_state`, `right_state`, `penalty` (default 300), `description`.
- `CoverCheckboxSchema` — frozen, slots: `family`, `groups`, `constraints`.
- `STATUTORY_CHECKBOX_CONSTRAINTS` — seven constraints: `wksi_shell_exclusion`,
  `wksi_voluntary_filer_exclusion`, `wksi_12_month_compliance`,
  `wksi_404b_required`, `shell_404b_exemption`, `egc_wksi_exclusion`,
  `recovery_requires_error_correction`.
- `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA` — both carry the same
  three groups (`report_period`, `filer_status`, `statutory_binary`) and the same
  seven constraints.
- Group and item constants: `REPORT_PERIOD_GROUP`, `FILER_STATUS_GROUP`,
  `STATUTORY_BINARY_GROUP`, `REPORT_ANNUAL`, `REPORT_QUARTERLY`,
  `REPORT_TRANSITION`, `FILER_LARGE_ACCELERATED`, `FILER_ACCELERATED`,
  `FILER_NON_ACCELERATED`, `FILER_SMALLER_REPORTING`, `FILER_EMERGING_GROWTH`,
  `STAT_WKSI`, `STAT_SHELL`, `STAT_VOLUNTARY`, `STAT_COMPLIANT_12_MONTHS`,
  `STAT_SOX_404B`, `STAT_EGC_TRANSITION_OPTOUT`, `STAT_ERROR_CORRECTION`,
  `STAT_RECOVERY_ANALYSIS`, `FILER_STATUS_TERMS`.

Checkmark tokens — `edgar_sec/domain/forms/checkmarks.py`:

- `CANONICAL_CHECKED` / `CANONICAL_UNCHECKED` — `"[X]"` / `"[ ]"`.
- `CheckmarkScope` — `StrEnum`: `GLOBAL_SAFE`, `COVER_CONTEXT`, `ALL`.
- `CheckmarkDecision` — frozen, slots: `source_token`, `canonical_token`,
  `state`, `scope`, `confidence`, `reason`, `source_region`, `span`.
- `CHECKED_TOKENS` / `UNCHECKED_TOKENS` — `frozenset`s built from
  `RAW_CHECKED_TOKENS` / `RAW_UNCHECKED_TOKENS` (symbols, HTML entities, and
  every `BRACKET_PAIRS` × `CHECKED_INNER` / `UNCHECKED_INNER` product).
- `BARE_MARK_TOKENS` — `("x", "X", "o", "O", "þ", "ý", "r", "R")`.
- `CONTEXT_CHECKED_SYMBOLS` / `CONTEXT_UNCHECKED_SYMBOLS` — filled geometric
  glyphs reserved for explicit filer-grid geometry, not general marks.
- `FONT_GLYPH_MAPPINGS` / `FONT_BULLET_GLYPH_MAPPINGS` — per symbolic font
  (`wingdings`, `wingdings 2`, `wingdings2`, `webdings`, `symbol`).
- `font_glyph_state(font_family, glyph)` /
  `font_bullet_glyph_state(font_family, glyph)` — resolve a glyph through a
  comma-separated font stack; `None` when the family is not a mapped one.
- `CHECKMARK_MARK_RE`, `RE_VARIABLE_CHECKED`, `RE_VARIABLE_UNCHECKED`,
  `RE_RAW_CHECKED`, `RE_RAW_UNCHECKED` — the sanctioned accessors.
- `is_unchecked_mark_token(value)`, `is_fill_in_mark_token(value)`.

Vocabulary — `edgar_sec/domain/forms/vocabulary.py`:

- `COVER_LABELS` — eight canonical cover concepts
  (`state_of_incorporation`, `irs_ein`, `principal_address`, `zip_code`,
  `telephone`, `registrant_name`, `commission_file_number`, `securities_12b`)
  each mapped to its observed alias phrases; `COVER_LABELS_FLAT` is the
  flattened tuple.
- `SECURITIES_12B_ANCHOR_TERMS` / `SECURITIES_12B_SUPPORT_TERMS` — the split
  between a decisive 12(b) table caption and a corroborating one.
- The eight compiled label patterns: `STATE_INCORPORATION_RE`, `IRS_EIN_RE`,
  `ADDRESS_RE`, `ZIP_RE`, `TELEPHONE_RE`, `REGISTRANT_NAME_RE`,
  `COMMISSION_FILE_RE`, `SECURITIES_12B_RE`.
- Value patterns: `ZIP_VALUE_RE`, `EIN_VALUE_RE`, `COMMISSION_FILE_VALUE_RE`.
- Shape detectors: `CURRENCY_SPACING_RE`, `PUNCT_SPACING_RE`,
  `IXBRL_FACT_RE`, `SEC_HEADER_TERMS`, `COVER_START_IDENTITY_TERMS`,
  `COVER_START_SHAPE_TERMS`, `COVER_EVIDENCE_TERMS`.
- Checkbox grids: `CHECKBOX_KEYWORDS`, `CHECKBOX_GRID_RE`,
  `FILER_CATEGORY_PATTERNS`, and the eight `LARGE_ACCELERATED_FILER` …
  `VOLUNTARY_FILER` filer-status constants.
- `is_state_value(value)` — membership test against a 102-entry private set of
  state names and postal codes.

Body evidence — `edgar_sec/domain/forms/body_evidence.py`:
`BODY_STRONG_PHRASES`, `BODY_SOFT_PHRASES`, `BODY_STRONG_TERMS`, `BODY_VERBS`,
`BODY_WEAK_TERMS`, `BODY_FORWARD_TERMS`, `COVER_EXCLUSION_TERMS`,
`BODY_SEMANTIC_HEADINGS`.

Decisions — `edgar_sec/domain/forms/decisions.py`: `DecisionAction`,
`EvaluatorDecision` (`action`, `target_exhibit`, `reason`, `is_stub`,
`category`, `confidence`, `metadata`).

## Tests

```text
tests/domain/forms/test_checkmarks.py    4 test functions, 50 lines
tests/domain/forms/test_decisions.py     2 test functions, 25 lines
tests/domain/forms/test_families.py      6 test functions, 67 lines
tests/domain/forms/test_schemas.py       3 test functions, 40 lines
```

## Deliberate gaps

- **`vocabulary.py` and `body_evidence.py` have no mirrored test file.** They are
  469 and 161 lines — together 40% of the package — and `vocabulary.py` is the
  largest single module in all of Layer 1. `AGENTS.md` §6.3 requires one test
  file per source module; `tests/domain/forms/test_vocabulary.py` and
  `tests/domain/forms/test_body_evidence.py` do not exist. Their constants are
  exercised only indirectly, by the engine tests that consume them
  (`tests/engine/forms/...`). This is a coverage gap in the test tree, not an
  intentional omission of testing.
- **`family_vocab.py`'s form aliases are duplicated in the engine.**
  `families.py`'s docstring claims "The engine and every pipeline resolve
  families through this table; no consumer owns a private alias list", but
  `engine/selection/features.py:58` declares its own byte-identical
  `FORM_FAMILY_SUFFIXES` and `:92` its own byte-identical `form_family()`. The
  duplication is deliberate on the engine's side — `form_family_sql()` at
  `:105` generates the SQL equivalent from the local tuple, so the SQL and
  Python forms cannot drift apart — but it does mean two suffix lists exist and
  they must be changed together. The engine's copy omits the `FORM_FAMILY_ALIASES`
  lookup entirely; only this package resolves `10-K405` to `10-K`.
- **The US state list is duplicated and the two copies differ.**
  `vocabulary.py:301` holds a private `_US_STATES` of 102 entries (51 postal
  codes plus 51 uppercase full names) backing `is_state_value()`.
  `taxonomy/jurisdictions.py:16` holds `STATE_POSTAL_CODES` of 54 entries and
  `STATE_NAMES` of 54 lowercase full names. The shared 51 codes are identical;
  `vocabulary.py` has no `PR`, `VI`, or `GU`, and `jurisdictions.py` has no
  uppercase full names. Neither module records why the two exist, so treat the
  difference as an open question rather than a documented decision. The
  natural resolution is for `is_state_value()` to consult `taxonomy`.
- **v1's per-form evidence packs were collapsed into one generic pack.**
  `body_evidence.py:8-12` records the divergence: v1 carried one pack per form
  (annual / quarterly / current report) differing only in vocabulary breadth,
  and the annual pack was a superset of the other two for every tier the
  boundary actually consults, so v2 ships a single pack. Per-form tuning is
  therefore not available and would need a new module, not a new constant.
- **"may" is deliberately absent from `BODY_FORWARD_TERMS`.** The module says
  why at `body_evidence.py:98-99`: fold-mode matching would also match the month
  name "May". Do not add it without changing the matching mode, not the list.
- **`DecisionAction` has three members, not four.**
  `roadmap/refactor_v2/v2_refactor_roadmap.md:99` and
  `phase_2_5/01_foundation_and_domain.md:31` both record that the wider
  multi-scope design (`REFETCH_BUNDLE`, `REFETCH_SUMMARY_XML`, EX-21/EX-10
  targeting) is a future extension; only `REFETCH_SUB_DOC` targeting Exhibit 13
  was ever exercised. This is a deliberate narrowing, not an incomplete port.
- **Most of v1's `defs/sec_forms/` is not here.** v1 additionally carried
  `sequences.py` (phrase-sequence healing rules), `concepts.py` (`ConceptPattern`
  for regex/BoW dual matching), `models.py` (`CoverPageModel`, `Security12b`,
  `RegistrantEntry`, `CheckboxDisclosures`), the `page_markers/` tree, and
  per-form `forms/annual|quarterly|current_report/` taxonomies. None has a v2
  counterpart in this package.
  `roadmap/refactor_v2/v2_refactor_roadmap.md:1244` records 99.3% of the six
  named packages as `NOT_STARTED` and notes that a prior doc claim that the
  checkmark solver was "functionally intact" is stale. `PenaltyScorer`,
  `HypothesisScore`, `CoverCheckmarkResult`, `ConstraintViolation`, and
  `infer_cover_checkmarks` have zero hits in `edgar_sec/` and `tests/`.
- **`CONTEXT_CHECKED_SYMBOLS` is geometry-gated by convention, not by type.**
  `checkmarks.py:73` comments that filled geometric glyphs "remain available for
  explicit filer-grid geometry", but the glyph sets are plain tuples with no
  marker distinguishing them; the scope is the caller's to apply.
