# `edgar_sec/engine/company_family` — deterministic company-name normalization and family clustering

Collapses the many CIKs one economic entity files under into a single family, so that a
mortgage trust filing once per deal does not swamp a quota-balanced sample. It owns name
normalization and the two-pass clustering that resolves variants, roots, and orphans into
families with a canonical representative.

## Purpose

One economic entity, many CIKs. "Santander Drive Auto Receivables Trust 2007-2" and
"Santander Drive Auto Receivables Trust 2013-2" are the same company with a different deal
number. Left alone, a single corporate family dominates any quota-based sample, and research
drawn from it inherits one company's filing history.

The package answers that with a fixed two-pass algorithm over a registrant corpus:

- **Pass 1** classifies each name as a *pure root* (no structural tokens), a *protected root*,
  a *series variant*, or an *orphan* (no usable body or key), and mines the structural tail
  vocabulary that separates the two trust names above.
- **Pass 2** groups variants by their first two key tokens, resolves head aliases, attaches
  plausible parent registrants, and picks a representative name.

Everything is in-memory and deterministic: no I/O beyond the two explicit factory methods, no
dependence on dict ordering or wall-clock state (`clustering.py:15-16`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalizer.py` | The pure name pipeline. `normalize_name` (jurisdiction and trademark stripping, tokenizing, abbreviation expansion, plural folding), `post_normalize` (digits, single letters, and roman numerals to placeholders), `strip_legal_forms`, `normalized_body` (the full chain), plus the structural-vocabulary primitives `first_structural_index`, `count_structural_tokens`, `clean_key`, `is_variant`, `is_plausible_parent`, `mine_structural_vocabulary`. |
| `clustering.py` | The two-pass resolver. `CompanyFamilyIndex` with factories `build_from_seed` (a CIK/name CSV manifest) and `from_existing_profiles` (a materialized `company_profiles.parquet`) and the core `build_from_records`; lookups `resolve` and `derive_company_family`; the `CompanyFamilyInfo` record; `family_id_for`. Private helpers: `_resolve_head_aliases`, `_attach_roots`, `_choose_representative`, `_register`, `_shared_prefix_length`, `_representative_rank`. |

## Contracts

- **Normalization is a total, pure function of its input.** `normalize_name("")` returns `[]`;
  a name that is entirely punctuation returns `[]` after tokenizing
  (`normalizer.py:46-62`). The same name always normalizes identically.
- **The normalization order is fixed and load-bearing.**
  `normalized_body` = `strip_legal_forms(post_normalize(normalize_name(name)))`
  (`normalizer.py:108-110`). `post_normalize` must run *after* abbreviation expansion, because
  expanding `intl` to `international` changes what counts as a single letter; and legal forms
  must be stripped *last*, because `strip_legal_forms` is a set membership test against
  `edgar_sec.domain.taxonomy.legal_forms.LEGAL_FORMS` on already-folded tokens.
- **A series number is not part of identity.** `post_normalize` collapses any all-digit token to
  `DIGIT_PLACEHOLDER = "D"`, any single alpha character to `"S"`, and any roman numeral to
  `"R"` (`normalizer.py:39-41`, `:84-100`). This is why `2007-2` and `2013-2` do not split one
  trust into two families.
- **Structural vocabulary is mined, not hand-listed.** `mine_structural_vocabulary` marks a
  token structural when it appears often enough in the *tail* of names (after
  `HEAD_TOKENS = 3`) and rarely enough in the *head* — a `prefix_share < 0.35` guard is what
  protects real words, so a token heading most of the names that carry it is treated as identity
  rather than boilerplate (`normalizer.py:198-207`). Thresholds relax below ~100 names: the
  minimum tail frequency drops to 1 and the minimum name length to 3
  (`normalizer.py:176-180`).
- **A single shared token never merges two companies.** `_attach_roots` requires a two-token
  shared prefix, a root strictly inside a head, or a head that is a prefix of the root. The
  docstring names the case this exists for: "that is what keeps 'Honda Motor' and 'Honda Auto'
  apart" (`clustering.py:385-388`). A one-token root is further gated on that token heading
  exactly one family and having exactly one continuation (`clustering.py:400-412`).
- **Head aliasing only fires on an unambiguous prefix.** A head aliases to a longer head only
  when exactly one candidate extends it; when several do, neither is aliased
  (`clustering.py:348-367`). Alias chains are then followed to a fixed point with a `visited`
  set, so a cycle introduced by a later assignment cannot hang the build
  (`clustering.py:230-235`).
- **Representation is chosen by value, never by arrival order.** `_representative_rank` orders
  candidates as `(priority, len(body), sha256(seed_string + name), name)`, where priority is 0
  for a zero-count record, 1 for a plausible parent, and 2 otherwise
  (`clustering.py:77-97`). The hash tiebreak is what makes the result stable no matter how the
  corpus was ordered.
- **The index is frozen after construction.** `CompanyFamilyIndex.__init__` wraps both lookup
  dicts in `MappingProxyType` and the vocabulary in `frozenset` (`clustering.py:105-115`), so a
  caller mutating it mid-resolution cannot make results depend on call order.
- **Resolution never fails.** `CompanyFamilyIndex.resolve` falls back to a stateless
  `derive_company_family` when the CIK and the name are both unknown
  (`clustering.py:289-314`). The reason is practical: the selection feature builder walks every
  filing in the catalog, and the catalog names registrants that were absent from the seed
  manifest. Those rows stay usable instead of being dropped.
- **There is no process-wide memo.** `build_from_seed` explicitly does not cache previous
  builds: "a cache keyed on a filesystem mtime is hidden global state that leaks memory and
  makes results depend on call order" (`clustering.py:129-132`).
- **Layer discipline.** Both modules import only `domain.taxonomy`, `domain.sec_urls`,
  `foundation.regex`, and — inside `from_existing_profiles` only — `infra.storage` (a function-local
  import at `clustering.py:158-159`). Never `pipelines`.

## Public surface

- `CompanyFamilyIndex` — the resolver. `build_from_seed(seed_path, seed_string=SEED)`,
  `from_existing_profiles(profiles_path, seed_string=SEED)`,
  `build_from_records(records, seed_string=SEED)`, `resolve(cik, company_name="")`,
  `derive_company_family(name)`, `__len__`.
  `edgar_sec/engine/company_family/clustering.py:100`.
- `CompanyFamilyInfo` — `cik`, `company_name`, `family_id`, `family_key`,
  `representative_name`, `is_variant`. `edgar_sec/engine/company_family/clustering.py:54`.
- `family_id_for` — the 12-character SHA-256 prefix of the space-stripped family key.
  `edgar_sec/engine/company_family/clustering.py:65`. `FAMILY_ID_LENGTH = 12` at `:50`.
- `normalize_name` — tokenize and expand abbreviations, context-sensitively.
  `edgar_sec/engine/company_family/normalizer.py:44`.
- `post_normalize` — collapse digits, single letters, and roman numerals to placeholders.
  `edgar_sec/engine/company_family/normalizer.py:84`.
- `strip_legal_forms` — drop legal and entity-type suffixes.
  `edgar_sec/engine/company_family/normalizer.py:103`.
- `normalized_body` — the full chain; the comparable token body.
  `edgar_sec/engine/company_family/normalizer.py:108`.
- `first_structural_index` — the index of the first structural token, or `len(body)`.
  `edgar_sec/engine/company_family/normalizer.py:113`.
- `count_structural_tokens` — how many structural tokens the body carries.
  `edgar_sec/engine/company_family/normalizer.py:127`.
- `clean_key` — the family key: the body up to the structural boundary, placeholders removed.
  `edgar_sec/engine/company_family/normalizer.py:136`.
- `is_variant` — a series variant rather than a parent.
  `edgar_sec/engine/company_family/normalizer.py:142`.
- `is_plausible_parent` — short enough to be the family's parent name
  (`len(body) <= MAX_PARENT_TOKENS`). `edgar_sec/engine/company_family/normalizer.py:152`.
- `mine_structural_vocabulary` — mine the shared structural tail vocabulary from a corpus.
  `edgar_sec/engine/company_family/normalizer.py:157`.
- `PUNCT_RE` / `TRADEMARK_RE` — the two name-level patterns; `TRADEMARK_RE` is built through
  `edgar_sec.foundation.regex.builder.build_alternation`, per the `regex-alternations` scanner
  (`normalizer.py:31`, `:34-37`).
- `DIGIT_PLACEHOLDER` / `SINGLE_LETTER_PLACEHOLDER` / `ROMAN_PLACEHOLDER` — `"D"`, `"S"`, `"R"`.
  `edgar_sec/engine/company_family/normalizer.py:39-41`.

The tuning constants — `SEED`, `HEAD_TOKENS = 3`, `MIN_ALIAS_CHARS = 6`,
`MIN_CLUSTER_ATTACH = 2`, `MAX_PARENT_TOKENS = 4`, `STRUCTURAL_THRESHOLD = 1`, `PLACEHOLDER` —
are owned by `edgar_sec/domain/taxonomy/family_vocab.py` (204 lines), not here. That module is
entity vocabulary and is documented there.

## Tests

- `tests/engine/company_family/test_clustering.py` (361 lines) — pins the invariants rather than
  exact hash values: one economic entity collapses to one family; unrelated companies sharing
  one word stay apart.
- `tests/engine/company_family/test_normalizer.py` (70 lines) — parametrized over
  `TRADEMARK_RE` markers and the `normalize_name` / `post_normalize` chain.

## Deliberate gaps

- **No fuzzy matching, no embeddings, no external graph.** Families are derived from
  name structure alone. A subsidiary whose name shares no token prefix with its parent — an
  operating company trading under a completely different brand — resolves to its own family.
  That is the intended conservative behaviour, not an oversight, but it means family counts are
  a lower bound.
- **`is_year_token` is not defined here.** `edgar_sec/engine/tables/ascii_html/continuation.py`
  and `spans.py` import `is_year_token` from `edgar_sec/engine/tables/numeric_cells.py`; it does
  not exist in that module. The real definition is at
  `edgar_sec/foundation/text/dates.py` (`borders.py:11` imports it from there successfully). This
  is what currently makes the whole `ascii_html` package unimportable — see
  `edgar_sec/engine/tables/ascii_html/README.md`.
- **No persistence.** The index is built in memory and discarded. Nothing writes a
  family mapping artifact; the two factories read a seed CSV or a company-profiles Parquet, and
  `edgar_sec/engine/selection/features.py` copies the resolved `company_family` value into a
  DuckDB temp table (`_family_index` / `_FAMILY_MAP_DDL`, `features.py:78-79`) for the duration
  of one snapshot build. Rebuilding the index is cheap and deterministic, so there is nothing to
  cache.
- **No threshold for "too many families".** A corpus of one name produces one family; a corpus
  of a million unrelated names produces a million. `MIN_CLUSTER_ATTACH = 2` is the only size
  gate, and it governs *attaching a root to an existing family*, not whether a family forms.
- **`family_id_for` is SHA-256, and that choice is visible in every published plan.** The
  docstring is explicit: "Changing the algorithm changes every derived id, which is why it is
  pinned here rather than inlined at the call sites" (`clustering.py:70-72`). A plan whose
  `document_locator_key`-adjacent family ids were minted under a different algorithm will not
  match.
- **Nothing here is about forms.** `company_family` resolves *entity* identity. The adjacent
  question — collapsing `10-K/A` to `10-K` — is answered by
  `edgar_sec/engine/selection/features.py::form_family`, and form-family *aliases*
  (`10-KSB` → `10-K`) have no v2 home at all. See
  `edgar_sec/engine/selection/README.md`.
- **No CLI, no entry point.** The package is a library. The only production consumer is
  `edgar_sec/engine/selection/features.py`.
