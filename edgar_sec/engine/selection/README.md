# `edgar_sec/engine/selection` — the Phase 2 target-plan selector: quota-driven, family-capped candidate sampling

Answers the question deterministic planning cannot: not "which rows match these four filters"
but "which rows best fill a declared quota profile, without letting one corporate family or one
form crowd out the rest". It owns the policy, the feature snapshot, the bounded candidate
access, the five-phase deficit fill, and the feasibility statistics.

## Purpose

Planning slices a catalog on a handful of filters. Stratification is a different problem: a
policy may ask for 500 units with floors on 21 dimensions — at least 40 1990s filers in SIC
7372, at least 25 companies with a revival gap, at most 30% of any single era — and no single
SQL predicate expresses "the corpus is too thin in 1990s filers in that SIC band".

So the package works in two stages. `features.py` materialises a **feature snapshot**: one row
per filing occurrence with every stratifying dimension resolved, plus a companion row per
document locator. `selector.py` then fills a quota profile against that snapshot through five
ordered phases.

The design constraint that shapes everything is the **family cap**. A naive sample of filings is
dominated by large corporate groups, because a group with 400 subsidiaries files 400 documents.
Every candidate is keyed by a six-part classification signature —
`(company_family, form, era, sic_code, entity_type, lifecycle_class)` — and at most
`max_per_company_classification` candidates may share one signature. Because every subsidiary
resolves to one `company_family` (see `edgar_sec/engine/company_family/`), the cap suppresses
the group's subsidiaries without special-casing them.

## Layout

The package splits on the pure/impure seam, the same split
`edgar_sec/engine/company_family/` uses.

| Module | Responsibility |
| :--- | :--- |
| `policy.py` | Pure. The declarative `SelectionPolicy` (27 fields), `EraBand` with half-open year and date bounds, `SeedFiler` (carrying `cik`, `name`, `seed_group`, `coverage_tags`, `notes`), `KNOWN_DIMENSIONS` (the 21 names a policy may stratify on) and the two grain sets `LOCATOR_ONLY_DIMENSIONS` / `OCCURRENCE_ONLY_DIMENSIONS` that partition it, policy JSON serialization, the seed manifest vocabulary: `SEED_FILER_COLUMNS`, `load_seed_cik_csv`, `resolve_seed_filers`, `read_seed_filers_csv`, `write_seed_filers_csv`, plus `compute_seed_fingerprint`, `auto_generate_policy`, `discover_policies`, `normalize_value`. |
| `features.py` | I/O. `FeatureSnapshotBuilder` materialises the snapshot; the pure functions it wraps are `form_family`, `form_family_sql`, and `era_of`. Also `SnapshotPaths`, `FORM_FAMILY_SUFFIXES`, and the three tunables `DEFAULT_GAP_YEARS`, `DEFAULT_CESSATION_GRACE_YEARS`, `DEFAULT_STUB_SIZE_THRESHOLD`. |
| `source.py` | I/O. `CandidateSource` is the only component that opens a DuckDB connection, and it returns bounded pages. `CandidateFilters` builds the policy-level predicate once. `POOL_COLUMNS` (25) and `OCCURRENCE_COLUMNS` (26) are the two projections. |
| `selector.py` | The five-phase deficit fill: `DeficitSelector`, `SelectionResult`, `classification_signature`, `CLASSIFICATION_DIMENSIONS`, `DEFAULT_RESERVE_MAX_PAGES`. |
| `inventory.py` | Feasibility statistics, used to build the advisory `inventory_feasibility` block in a policy plan's `selection_report.json`. `InventoryStatistics.value_counts`, `check_floor_feasibility`, `check_composite_feasibility`; `LOCATOR_TABLE` / `OCCURRENCE_TABLE` name the snapshot files it counts. |

## The five phases

`DeficitSelector.select` (`selector.py:108-196`) runs in a fixed order of decreasing authority.
The order *is* the design:

1. **Seed filers** (`_select_seed_filers`, `selector.py:200`) — mandatory. A named anchor tenant
   appears in the output regardless of quota, and **seed filers bypass the family cap**
   (`record(candidate, check_cap=False)`, `selector.py:212`). This is inherited from v1 and
   deliberate: a cap that silently dropped a mandatory anchor would be worse than a slight
   over-representation.
2. **Composite strata** (`_select_composites`, `:214`) — conjunctions, so the hardest to satisfy,
   therefore attempted before single-dimension floors.
3. **Single-dimension floors** (`_select_floors`, `:233`) — chased by *relative* deficit, so the
   dimension proportionally furthest from its floor is fed first. Loops to
   `policy.max_pool_rounds` and stops early when a round makes no progress, because further
   rounds would re-query the same exhausted pools forever (`selector.py:261-264`).
4. **Weighted pool fill** (`_fill_weighted`, `:288`) — pages through the global tie-break order
   and takes whatever remains, subject to the declared share caps.
5. **The reserve** (`_select_reserve`, `:326`) — filled last, from candidates not in the active
   set, capped at `DEFAULT_RESERVE_MAX_PAGES = 100` pages. A reserve row is added to the
   exclusion set as it is taken, so it cannot also be admitted to the active set later
   (`selector.py:352`).

## Contracts

- **A parent selection is part of the selection, not a side input.** `select(parent_active_keys)`
  loads the parent's feature rows through `_account` before any phase runs, so they consume
  quota and register in coverage. The stated reason: "or an expansion would report coverage the
  published plan does not actually have" (`selector.py:165-167`). Duplicate keys in the parent
  list raise `ValueError` (`selector.py:126-127`).
- **Determinism is seeded, not incidental.** Every pool query orders by
  `sha256(CAST(? AS VARCHAR) || l.document_locator_key)` with the seed as a *bound parameter*
  (`source.py:113`). The seed must sit inside the concatenation, not beside it: DuckDB
  constant-folds `constant || column`, so `sha256(?) || key` would silently sort every row equal
  and the pool would come back in file order — deterministic-looking but seed-independent
  (`source.py:107-112`).
- **The pool is bounded by construction.** The selector never holds the candidate pool in
  memory. `pool_for_value`, `pool_for_composite`, `pool_for_ciks`, and `candidate_page` each
  take a `limit` and return at most that many rows, because "a corpus of millions of locators
  has to be selectable on a machine whose memory budget is derived from cgroup limits, not from
  the corpus" (`source.py:4-7`).
- **Every value reaching SQL is bound, and every column name is validated.** `_dimension`
  rejects anything outside `KNOWN_DIMENSIONS` (`source.py:227-231`); the tie-break seed is a
  `?` parameter; composite filters bind their values. This closes three v1 defects recorded at
  `source.py:9-23`: an interpolated seed (a policy file was a SQL injection surface), chunked
  `IN` lists re-parsed per chunk, and an interpolated dimension name that could query any
  column the snapshot happened to carry.
- **Row-to-dict mapping is strict.** `dict(zip(POOL_COLUMNS, row, strict=True))`
  (`source.py:225`, `:377`) — a projection that drifts from its column tuple raises rather than
  silently truncating every row.
- **The session is in-memory and its lifetime is scoped.** `CandidateSource.session()` opens one
  connection and creates the three working temp tables (`selected_keys`,
  `requested_locator_keys`, `requested_ciks`) in a `try/finally`. The comment records why:
  v1 opened a `selection_session.duckdb` inside the snapshot directory and deleted it
  afterwards, leaving a partially written database whenever the process died mid-run
  (`source.py:190-194`).
- **Feature building is a pure function of its inputs.** `snapshot_dir(forms)` hashes
  `(target_root, profile_path, sorted forms, options, policy_fingerprint)` and truncates to 32
  characters (`features.py:197-206`); `build()` returns the existing paths unchanged if the
  manifest is already there (`features.py:637-638`). Two runs of the same policy against the
  same catalog cannot disagree.
- **Date-bound reasoning lives only in `policy.py`.** `EraBand.matches` is the sole arbiter of
  what a date means; `features.era_of` maps a date onto a band and returns `"unknown"` rather
  than raising, so a filing with no usable report date stays visible instead of being dropped
  (`features.py:124-141`). Bounds are half-open, which is what lets adjacent bands tile a range
  without overlap.
- **The policy is validated where it is written.** `SelectionPolicy.__post_init__` rejects an
  unknown dimension *anywhere* — in `floors`, `weights`, `caps`, `value_weights`, or inside a
  composite's `filters` (`policy.py:295-305`). v1 checked only the top-level names, so a typo
  inside a composite survived construction and produced an unmatchable stratum.
- **Layer discipline.** This package imports `domain.filing_catalog`, `domain.sec_urls`,
  `domain.taxonomy`, `engine.company_family`, `foundation`, and `infra.storage`. It never imports
  `pipelines`; where it needs a Layer 4 path it takes a parameter instead (see
  `auto_generate_policy`, `discover_policies`).
- **No entry point.** There is no CLI and no `python -m edgar_sec.engine.selection`. The only
  production callers are Layer 4:
  `edgar_sec/pipelines/filing_catalog/planner.py` (`FeatureSnapshotBuilder`, `DeficitSelector`),
  `expansion.py` (`SelectionPolicy`, `compute_seed_fingerprint`), `cli.py`, and `discovery.py`.

## Public surface

- `SelectionPolicy` — the declarative quota profile (27 fields); `__post_init__` validates,
  `to_dict` / `to_json` / `from_dict` / `from_json` / `from_path` / `write` serialize,
  `policy_fingerprint` and `requested_units` are derived.
  `edgar_sec/engine/selection/policy.py:224`.
- `EraBand` — a bounded year or date interval with `matches(year, date_str)`.
  `edgar_sec/engine/selection/policy.py:81`.
- `SeedFiler` — one normalized row of the seed CIK manifest.
  `edgar_sec/engine/selection/policy.py:152`.
- `KNOWN_DIMENSIONS` — the 21 stratifiable dimension names.
  `edgar_sec/engine/selection/policy.py:49`.
- `POLICY_SCHEMA_VERSION` — `"1.0"`. `edgar_sec/engine/selection/policy.py:45`.
- `load_seed_cik_csv` — parse and validate a seed CIK CSV, normalizing every CIK to ten digits;
  falls back from `seed-cik.csv` to a sibling `cik-sec.csv`. `edgar_sec/engine/selection/policy.py:165`.
- `compute_seed_fingerprint` — hash the seed set *by value*, sorted by CIK, so re-sorting the
  manifest does not invalidate every plan built from it. `edgar_sec/engine/selection/policy.py:209`.
- `auto_generate_policy` — derive a baseline policy from a catalog's observed forms and year
  range. Takes the two facts as parameters, not paths, because Layer 3 may not reach the Layer 4
  catalog layout. `edgar_sec/engine/selection/policy.py:395`.
- `discover_policies` — summarize valid policy documents in the given directories; unparseable
  JSON is skipped, not raised. `edgar_sec/engine/selection/policy.py:429`.
- `normalize_value` — collapse `None` and the literal `"none"` into one bucket, so a floor on
  `"none"` is not permanently unmet. `edgar_sec/engine/selection/policy.py:471`.
- `FeatureSnapshotBuilder` — build or reuse the snapshot; `snapshot_dir(forms)`,
  `paths_for(dir)`, `build()`. `edgar_sec/engine/selection/features.py:164`.
- `SnapshotPaths` — `snapshot_dir`, `manifest`, `occurrence_features`, `locator_features`.
  `edgar_sec/engine/selection/features.py:145`.
- `form_family` — collapse amendment and submission suffixes to a base family; a form that is
  *entirely* suffixes collapses to the original, not to an empty dimension.
  `edgar_sec/engine/selection/features.py:92`.
- `form_family_sql` — the SQL twin, **generated** from `FORM_FAMILY_SUFFIXES` so the two cannot
  diverge; rejects any column identifier outside `[A-Za-z_][A-Za-z0-9_.]*`.
  `edgar_sec/engine/selection/features.py:110`.
- `era_of` — map a report date onto the first matching band, or `"unknown"`.
  `edgar_sec/engine/selection/features.py:124`.
- `FORM_FAMILY_SUFFIXES` — the ordered seven-suffix tuple.
  `edgar_sec/engine/selection/features.py:58`.
- `CandidateSource` — the bounded candidate accessor: `session()`, `pool_for_value`,
  `pool_for_composite`, `pool_for_ciks`, `candidate_page`, `register_selected`,
  `add_selected`, `load_candidates_for_locators`, `load_occurrences_for_locators`.
  `edgar_sec/engine/selection/source.py:157`.
- `CandidateFilters` — `amendment`, `document_suffixes`, `max_reported_size`; `.predicate()`
  builds the SQL once. `edgar_sec/engine/selection/source.py:126`.
- `POOL_COLUMNS` / `OCCURRENCE_COLUMNS` — the two projections (25 and 26 names), defined as
  tuples so the SELECT list and the row-to-dict zip come from one source.
  `edgar_sec/engine/selection/source.py:42` and `:72`.
- `SelectionSessionError` — a query attempted outside an open session.
  `edgar_sec/engine/selection/source.py:121`.
- `DeficitSelector` — `select(parent_active_keys=None)`.
  `edgar_sec/engine/selection/selector.py:88`.
- `SelectionResult` — `active_locators`, `active_candidates`, `active_occurrences`,
  `reserve_locators`, `reserve_candidates`, `report`. `edgar_sec/engine/selection/selector.py:62`.
- `classification_signature` / `CLASSIFICATION_DIMENSIONS` — the capped six-tuple, falling back
  to `company_name` when no family resolved so an unclustered candidate still participates in
  the cap. `edgar_sec/engine/selection/selector.py:73` and `:47`.
- `DEFAULT_RESERVE_MAX_PAGES` — `100`. `edgar_sec/engine/selection/selector.py:58`.
- `InventoryStatistics` — `value_counts`, `check_floor_feasibility`,
  `check_composite_feasibility`. `edgar_sec/engine/selection/inventory.py`.
- `UnknownDimensionError` — a statistic requested for a dimension outside the policy vocabulary.
- `OccurrenceOnlyDimensionError` — a composite stratum filtered on a dimension with no
  locator grain. `SelectionPolicy` refuses this at construction, so the class is the
  direct-API guard on the same rule. `edgar_sec/engine/selection/inventory.py`.
- `LOCATOR_ONLY_DIMENSIONS` / `OCCURRENCE_ONLY_DIMENSIONS` — the grain each dimension is counted
  at. A composite stratum selects from `locator_features`, so naming an occurrence-only
  dimension there is a policy error rather than an undersupplied stratum.
  `edgar_sec/engine/selection/policy.py`.

## Tests

- `tests/engine/selection/test_features.py` (276 lines)
- `tests/engine/selection/test_inventory.py` (171 lines)
- `tests/engine/selection/test_policy.py` (330 lines)
- `tests/engine/selection/test_selector.py` (393 lines)
- `tests/engine/selection/test_source.py` (286 lines)
- `tests/engine/selection/conftest.py` (264 lines) — the shared snapshot fixtures, at the
  narrowest directory that needs them per `AGENTS.md` §6.4.

## Deliberate gaps

- **This package does not own the corpus.** It reads two Parquet files
  (`locator_features.parquet`, `occurrence_features.parquet`) that a Layer 4 pipeline published
  into a snapshot directory. It has no ability to fetch, enumerate, or derive a filing catalog,
  and no way to discover a snapshot directory on its own — `discover_policies` requires
  `search_dirs` precisely because the default search location is a Layer 4 artifact-layout
  property and resolving it here would be an upward import (`policy.py:436-439`).
- **A cap that is not a cap is not enforced.** `_violates_cap` (`selector.py:308-324`) applies
  only during phase 4, the weighted pool fill. Phases 1-3 accept candidates through `_record`
  without consulting `policy.caps`, and phase 1 explicitly bypasses the family cap. The share
  caps are therefore a *fill-time* constraint, not an invariant of `SelectionResult`. A caller
  reading `report["underfilled_floors"]` should read it alongside the realised
  `coverage_distributions`, which is what `_build_report` publishes
  (`selector.py:378-398`).
- **No rebalancing pass.** Once `_select_floors` exhausts its rounds the underfilled floors are
  recorded and left underfilled; nothing swaps a selected candidate out to make room.
- **Feasibility is advisory, never a gate.** `check_floor_feasibility` and
  `check_composite_feasibility` run after selection and publish an
  `inventory_feasibility` block in the plan's `selection_report.json`, but they
  cannot fail a fresh plan: a shortfall is still reported in `underfilled_floors`
  rather than refused. Two reasons. The per-dimension counts are independent, so
  they do not subtract competition between floors, the family cap, or the seeds
  — a set of individually feasible floors can still underfill together. And a
  floor can be satisfiable yet skipped once a cap or an earlier phase has claimed
  the candidates. A prediction is weaker evidence than a completed selection.
  Making it a gate would need a joint model of the quotas, not per-dimension counts.
  The planner catches the three ways the inventory is known to decline — unknown
  dimension, occurrence-grain composite, unreadable snapshot — and records
  `checked: false` with the reason; an unexpected DuckDB error is deliberately
  left to propagate, since an unreadable snapshot is a broken run, not a shortfall.
- **A composite stratum cannot name an occurrence-grain dimension.** Composites
  are drawn from `locator_features`, which carries no `accession_class` column.
  `SelectionPolicy` construction refuses such a policy, naming the offending
  field, rather than letting it fail as a DuckDB Binder Error from inside
  selection. `OCCURRENCE_ONLY_DIMENSIONS` currently holds only
  `accession_class`: `sic_code` resolves at locator grain, because the locator
  projection carries the representative registrant's value. v1 classified
  `sic_code` as occurrence-only, which sent its counts to the wider table and
  made a composite filter on it look unmatchable.
- **The seed set is pinned by the plan, not by the policy path.** A policy names
  `seed_cik_path`, but `FeatureSnapshotBuilder` receives the already-normalized seed map
  and never re-reads the file. This means a builder constructed directly with a
  `seed_cik_path` set and no `seed_filers` will fall back to profile-derived company
  families, ignoring the configured file. The pipeline always resolves the seed set first
  (`resolve_seed_filers`) and passes it in, so this only affects direct API use.
- **v1's form-family alias registry has no v2 home here.** v1's
  `defs/sec_forms/families.py` carried `FORM_FAMILY_ALIASES` (30 entries: `10-K405`, `10-KSB`,
  `10KSB40`, `10-KT`, `10KT405`, `10-QSB`, `10-QT`, `8-K12B`, `8-K12G3`, `8-K15D5`,
  `20FR12B`, `20FR12G3`) plus `resolve_alias` / `normalize_form` / `aliases_for_family` /
  `family_lookup`. v2's `form_family` collapses *suffixes* only, so it maps `10-K/A` → `10-K` but
  has no answer for `10-KSB`. `edgar_sec/domain/taxonomy/family_vocab.py` does not cover it
  either — that module is company-*name* vocabulary. Roadmap
  `roadmap/refactor_v2/v2_refactor_roadmap.md` sec.1.4 flags this as a correction: form-family
  classification is a *selection* concern, built by `form_family()` here and emitted into the
  snapshot.
- **No form-name validation against a vocabulary.** `SelectionPolicy.forms` is upper-cased,
  de-duplicated, and required to be non-empty, but `"NOT-A-FORM"` passes construction. A
  nonexistent form produces a snapshot with zero rows rather than an error.
- **No CLI, no plan writer, no manifest.** This package produces `SelectionResult` values. Writing
  `plan.json`, recording provenance, and persisting a work order are Layer 4
  (`edgar_sec/pipelines/filing_catalog/`). `SelectionPolicy.write` is the single exception: it
  writes a policy document, atomically, via `infra.storage.atomic.atomic_write_json`
  (`policy.py:333-344`).
- **The report is a plain dict, not a typed record.** `SelectionResult.report` has no schema and
  no version field; a caller reading `underfilled_floors` is depending on an undocumented key.
- **Do not confuse this with v1's `defs/taxonomy/`.** v1's `defs/taxonomy/` was a financial
  *table* classifier; v2's `edgar_sec/domain/taxonomy/` is entity *vocabulary*
  (`family_vocab.py`, `jurisdictions.py`, `legal_forms.py`). The names collide; the subjects do
  not. Neither is the quota model this package implements.
