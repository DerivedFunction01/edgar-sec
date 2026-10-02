# `edgar_sec/engine/selection` — quota-driven, family-capped target selection

Answers the question deterministic planning cannot: not "which rows match these five filters"
but "which rows best fill a declared quota profile, without letting one corporate family or one
form crowd out the rest".

## Purpose

A plan may ask for 500 units with floors on 21 dimensions and share caps on the rest. No single
SQL predicate expresses "the corpus is too thin in 1990s filers in that SIC band", so selection
works in two stages. `features.py` materialises a **feature snapshot** — one row per filing
occurrence with every stratifying dimension resolved, plus a companion row per document
locator. `selector.py` then fills a quota profile against that snapshot through five ordered
phases.

The load-bearing constraint is the **family cap**. A naive filing sample is dominated by large
corporate groups, because a group with 400 subsidiaries files 400 documents. Every candidate is
keyed by the six-part signature `(company_family, form, era, sic_code, entity_type,
lifecycle_class)` — `CLASSIFICATION_DIMENSIONS`, the same tuple the root
[README](../../../README.md) documents — and at most `max_per_company_classification`
candidates may share one signature (default 1; `None` disables it). Since every subsidiary
resolves to one `company_family` (see [`../company_family/`](../company_family/README.md)), the
cap suppresses the group without special-casing it.

## Layout

Split on the pure/impure seam, the same split `../company_family/` uses.

| Module | Responsibility |
| :--- | :--- |
| `policy.py` | Pure. `SelectionPolicy` (24 fields, validated in `__post_init__`) with its `to_dict`/`from_path`/`write` serialization; `EraBand` with half-open year and date bounds; `SeedFiler` and the `SEED_FILER_COLUMNS` manifest vocabulary (`load_seed_cik_csv`, `read_seed_filers_csv`, `write_seed_filers_csv`, `resolve_seed_filers`, `compute_seed_fingerprint`); `KNOWN_DIMENSIONS` — the 21 stratifiable names — partitioned by grain into `LOCATOR_ONLY_DIMENSIONS` / `OCCURRENCE_ONLY_DIMENSIONS`; `auto_generate_policy`, `discover_policies`, `normalize_value`. |
| `features.py` | I/O. `FeatureSnapshotBuilder` builds or reuses the snapshot; `SnapshotPaths` names its four files. The pure functions it wraps are `form_family`, `form_family_sql`, `era_of`. Tunables: `DEFAULT_GAP_YEARS`, `DEFAULT_CESSATION_GRACE_YEARS`, `DEFAULT_STUB_SIZE_THRESHOLD`. |
| `source.py` | I/O. `CandidateSource` returns bounded pages over one in-memory DuckDB session; `CandidateFilters` builds the policy predicate once. `POOL_COLUMNS` (25) and `OCCURRENCE_COLUMNS` (26) are the two projections. |
| `selector.py` | The six-phase deficit fill: `DeficitSelector`, `SelectionResult`, `classification_signature`, `CLASSIFICATION_DIMENSIONS`, `DEFAULT_RESERVE_MAX_PAGES`. |
| `inventory.py` | Feasibility statistics for the advisory `inventory_feasibility` block a Layer 4 plan publishes: `InventoryStatistics`, `UnknownDimensionError`, `OccurrenceOnlyDimensionError`. |

## Contracts

- **Network-free, and proved rather than asserted.** `edgar_sec.engine.selection` is a
  registered member of `OFFLINE_PACKAGES` in
  [`tests/test_network_isolation.py`](../../../tests/test_network_isolation.py), which AST-walks
  every module in the package and fails if `edgar_sec.infra.sec_http` is transitively reachable.
  The walk resolves 24 `edgar_sec` modules and none of them is the HTTP client. This is what
  lets [`pipelines/filing_catalog/`](../../pipelines/filing_catalog/README.md) claim it performs
  no network I/O at all.
- **A parent selection is part of the selection, not a side input.** `select` loads the parent's
  feature rows through `_account` before any phase runs, so they consume quota and register in
  coverage — otherwise an expansion would report coverage the published plan does not have.
  Duplicate parent keys raise `ValueError`.
- **Phase order is the design.** The six phases run in fixed order of decreasing authority:
  mandatory seeds, composite strata, single-dimension floors by relative deficit, **form-by-era
  allocation**, weighted pool fill, reserve. Allocation sits before the weighted fill because that
  fill is proportional: whichever form is largest would otherwise take the whole leftover budget,
  and a rare form would appear only as far as a declared floor pushed it. Allocation reads cell
  availability once, visits cells era-first so a cap smaller than the cell count still gives every
  era one row, redistributes what an exhausted cell could not take across later rounds, and stops
  when a round is refused in full — which means the family cap, and re-querying would be refused
  identically. The remaining budget after the earlier phases is what it draws from, so the global
  cap is shared and a floor that already filled a cell is credited rather than given a second share.
- **A declared date selection is enforced by every pool, not applied afterwards.** `CandidateFilters`
  compiles it into the value, composite, seed-CIK, page, and cell-availability queries alike, so no
  phase can draw an out-of-range candidate even transiently to consume quota on the way to being
  dropped. An empty selection is no predicate and keeps rows with no readable `report_date`; a
  nonempty one cannot place such a row and excludes it.
- **An empty `era_bands` list means derived, not unstratified.** The caller resolves bands from
  the years the policy's own forms and date selection reach, because era is baked into the feature
  snapshot and a reader must not have to re-derive a stratification the locators were not chosen
  under. `SelectionPolicy` has no catalog access, so it declares the mode (`derives_era_bands`) and
  the resolver (`with_era_bands`) rather than deriving. Two consequences worth naming: **seed filers bypass the family cap**
  (`check_cap=False`) — a cap that silently dropped a mandatory anchor would be worse than a
  slight over-representation — and a reserve row is added to the exclusion set as it is taken, so
  it cannot also be admitted to the active set later.
- **Determinism is seeded, not incidental.** Every pool query orders by
  `sha256(CAST(? AS VARCHAR) || l.document_locator_key)` with the seed as a *bound parameter*.
  The seed must sit inside the concatenation: DuckDB constant-folds `constant || column`, so
  `sha256(?) || key` would sort every row equal and return the pool in file order —
  deterministic-looking, and seed-independent.
- **The pool is bounded by construction.** The selector never holds the candidate pool in memory.
  `pool_for_value`, `pool_for_composite`, `pool_for_ciks`, and `candidate_page` each take a limit
  and return at most that many rows, because a corpus of millions of locators has to be selectable
  on a machine whose memory budget derives from cgroup limits, not from the corpus.
- **Every value reaching SQL is bound; every column name is validated.** `_dimension` rejects
  anything outside `KNOWN_DIMENSIONS`, the seed is a `?` parameter, and composite filters bind
  their values. Row-to-dict mapping is `dict(zip(POOL_COLUMNS, row, strict=True))`, so a
  projection that drifts from its column tuple raises rather than silently truncating every row.
- **The session is in-memory and its lifetime is scoped.** `CandidateSource.session()` opens one
  connection and creates the three working temp tables (`selected_keys`,
  `requested_locator_keys`, `requested_ciks`) in a `try/finally`.
- **Feature building is a pure function of its inputs.** `snapshot_dir(forms)` hashes the target
  root, profile path, sorted forms, build options, the policy fingerprint and the seed
  fingerprint; `build()` returns the existing paths unchanged when the manifest is already there.
  Two runs of the same policy against the same catalog cannot disagree.
- **Date-bound reasoning lives only in `policy.py`.** `EraBand.matches` is the sole arbiter of
  what a date means; `features.era_of` maps a date onto a band or returns `"unknown"` rather than
  raising, so a filing with no usable report date stays visible instead of being dropped. Bounds
  are half-open, which is what lets adjacent bands tile a range without overlap.
- **The policy is validated where it is written.** `SelectionPolicy.__post_init__` rejects an
  unknown dimension *anywhere* — in `floors`, `caps`, or inside a composite's `filters` — and
  refuses a composite naming an occurrence-grain dimension.
- **A key nothing reads is not configuration.** `seed_groups`, `weights`, `value_weights`, and
  `policy_schema_version` were all carried and none was consulted: the final fill is sequential
  under the cap check rather than weighted, the seed CSV already labels each filer's own group,
  and the enforced schema version lives in the plan document that expansion checks. They are
  gone, and `from_dict` refuses a draft that still declares one rather than loading the rest —
  a silently dropped key would leave a policy whose text describes a weighting nothing applies.
  The enforced version is `publication.TARGET_PLAN_SCHEMA_VERSION`.
- **Layer discipline.** This package imports only `domain`, `foundation` and `infra.storage`,
  plus the sibling `engine.company_family`. Never `pipelines`; where it needs a Layer 4 path it
  takes a parameter instead (see `auto_generate_policy`, `discover_policies`).

## Command surface

None. There is no CLI and no `python -m edgar_sec.engine.selection`. The only production callers
are Layer 4: `pipelines/filing_catalog/planner.py` (`FeatureSnapshotBuilder`, `DeficitSelector`,
`InventoryStatistics`, and the policy/seed-manifest vocabulary), `expansion.py` (`SelectionPolicy`
and the seed sidecar), `discovery.py` (`SelectionPolicy`, `auto_generate_policy`,
`discover_policies`), and `cli.py`.

## Public surface

- **From `policy.py`** — `SelectionPolicy` (24 fields; `__post_init__` validates, `to_dict` /
  `to_json` / `from_dict` / `from_json` / `from_path` / `write` serialize, `policy_fingerprint`
  and `requested_units` are derived, `validate_dimensions` cross-checks against a snapshot,
  `date_selection_clauses` / `date_selection_text` / `derives_era_bands` decode the declared
  selection, and `with_era_bands` returns the resolved copy a plan embeds);
  `EraBand` (`matches(year, date_str)`); `SeedFiler`; `KNOWN_DIMENSIONS` (21 names); `LOCATOR_ONLY_DIMENSIONS` / `OCCURRENCE_ONLY_DIMENSIONS`;
  `SEED_FILER_COLUMNS` with `load_seed_cik_csv` / `read_seed_filers_csv` /
  `write_seed_filers_csv` / `resolve_seed_filers` / `compute_seed_fingerprint`;
  `auto_generate_policy`; `era_bands_for_range` (the automatic tiling a caller resolves against);
  `discover_policies`; `normalize_value`.
  `load_seed_cik_csv` normalizes every CIK to ten digits and falls back from `seed-cik.csv` to a
  sibling `cik-sec.csv`; `compute_seed_fingerprint` hashes the seed set *by value*, sorted by
  CIK, so re-sorting the manifest does not invalidate every plan built from it; `normalize_value`
  collapses `None` and the literal `"none"` into one bucket, so a floor on `"none"` is not
  permanently unmet.
- **From `features.py`** — `FeatureSnapshotBuilder` (`snapshot_dir(forms)`, `paths_for(dir)`,
  `build()`); `SnapshotPaths`; `form_family` (a form that is *entirely* suffixes collapses to the
  original, not to an empty dimension); `form_family_sql` (the SQL twin, **generated** from
  `FORM_FAMILY_SUFFIXES` so the two cannot diverge, rejecting any column identifier outside
  `[A-Za-z_][A-Za-z0-9_.]*`); `era_of`; the three `DEFAULT_*` tunables. `FORM_FAMILY_SUFFIXES` is
  re-exported here but owned by `domain/forms/common/aliases.py`.
- **From `source.py`** — `CandidateSource` (`session`, `pool_for_value`, `pool_for_cell`,
  `pool_for_composite`, `pool_for_ciks`, `cell_availability`, `candidate_page`,
  `register_selected`, `add_selected`, `load_candidates_for_locators`,
  `load_occurrences_for_locators`); `CandidateFilters` (`amendment`, `document_suffixes`,
  `max_reported_size`, `date_selection`, `.filters_dates()`, `.predicate()`); `POOL_COLUMNS` /
  `OCCURRENCE_COLUMNS`; `SelectionSessionError` (a query attempted outside an open session).
  `cell_availability` returns every nonempty `(form, era)` cell with its eligible count in one
  grouped pass, excluding the already-selected set so a drained cell is not counted as capacity.
- **From `selector.py`** — `DeficitSelector.select(parent_active_keys=None)`;
  `SelectionResult` (`active_locators`, `active_candidates`, `active_occurrences`,
  `reserve_locators`, `reserve_candidates`, `report`); `classification_signature` /
  `CLASSIFICATION_DIMENSIONS` — falling back to `company_name` when no family resolved, so an
  unclustered candidate still participates in the cap; `DEFAULT_RESERVE_MAX_PAGES` (`100`).
  The report carries `form_era_allocation` (per-cell availability, allocation, selection and
  shortfall, plus `equal_quota` and `unallocated`) alongside `date_selection_text`,
  `era_band_count`, and `derives_era_bands`.
- **From `inventory.py`** — `InventoryStatistics` (`value_counts`, `check_floor_feasibility`,
  `check_composite_feasibility`); `UnknownDimensionError` (a statistic requested for a dimension
  outside the policy vocabulary); `OccurrenceOnlyDimensionError` (a composite stratum filtered on
  a dimension with no locator grain — `SelectionPolicy` already refuses that at construction, so
  the class is the direct-API guard on the same rule); `LOCATOR_TABLE` / `OCCURRENCE_TABLE`.

## Mirrored tests

- `tests/engine/selection/test_policy.py`
- `tests/engine/selection/test_features.py`
- `tests/engine/selection/test_source.py`
- `tests/engine/selection/test_selector.py`
- `tests/engine/selection/test_inventory.py`
- `tests/engine/selection/conftest.py` — the shared snapshot fixtures, at the narrowest directory
  that needs them per `AGENTS.md` §6.

## Deliberate gaps

- **This package does not own the corpus.** It reads two Parquet files
  (`locator_features.parquet`, `occurrence_features.parquet`) that a Layer 4 pipeline published
  into a snapshot directory. It cannot fetch, enumerate, or derive a filing catalog, and it
  cannot discover a snapshot directory on its own — `discover_policies` requires `search_dirs`
  precisely because the default search location is a Layer 4 artifact-layout property and
  resolving it here would be an upward import.
- **Share caps are a fill-time constraint, not an invariant of `SelectionResult`.**
  `_violates_cap` runs only during phase 4. Phases 1–3 accept candidates through `_record`, which
  consults the signature cap but never `policy.caps`, and phase 1 explicitly bypasses the
  signature cap. Read `report["underfilled_floors"]` alongside the realised
  `coverage_distributions`, which is what `_build_report` publishes.
- **No rebalancing pass.** Once the floor rounds are exhausted the underfilled floors are recorded
  and left underfilled; nothing swaps a selected candidate out to make room for a deficit.
- **Feasibility is advisory, never a gate.** `check_floor_feasibility` and
  `check_composite_feasibility` publish an `inventory_feasibility` block after selection but
  cannot fail a fresh plan. Two reasons. The per-dimension counts are independent, so they do not
  subtract competition between floors, the family cap, or the seeds — a set of individually
  feasible floors can still underfill together. And a floor can be satisfiable yet skipped once a
  cap or an earlier phase has claimed the candidates. A prediction is weaker evidence than a
  completed selection; a gate would need a joint model of the quotas, not per-dimension counts.
  The planner records `checked: false` with a reason for the three known declines (unknown
  dimension, occurrence-grain composite, unreadable snapshot) and deliberately lets an unexpected
  DuckDB error propagate — an unreadable snapshot is a broken run, not a shortfall.
- **A composite stratum cannot name an occurrence-grain dimension.** Composites are drawn from
  `locator_features`, which carries no `accession_class`, so `SelectionPolicy` refuses such a
  policy by name rather than letting it surface as a DuckDB Binder Error from inside selection.
  `OCCURRENCE_ONLY_DIMENSIONS` holds only `accession_class`: `sic_code` resolves at locator
  grain, because the locator projection carries the representative registrant's value.
- **The seed set is pinned by the plan, not by the policy path.** A policy names `seed_cik_path`,
  but `FeatureSnapshotBuilder` receives the already-normalized seed map and never re-reads the
  file. A builder constructed directly with a `seed_cik_path` and no `seed_filers` therefore
  falls back to profile-derived company families, ignoring the configured file. The pipeline
  always resolves the seed set first (`resolve_seed_filers`) and passes it in, so this affects
  direct API use only.
- **No form-name validation against a vocabulary.** `SelectionPolicy.forms` is upper-cased,
  de-duplicated, and required to be non-empty, but `"NOT-A-FORM"` passes construction and yields
  a snapshot with zero rows rather than an error.
- **Form-family classification is shared vocabulary, not local.** `features.form_family` collapses
  *suffixes* only, so `10-K/A` → `10-K` but `10-KSB` has no answer here. Canonical aliases
  (`10-KSB` → `10-K`, 30 entries) plus `resolve_alias` / `aliases_for_family` live in
  `domain/forms/common/aliases.py`, which also owns `FORM_FAMILY_SUFFIXES`. Separately,
  `domain/taxonomy/family_vocab.py` is company-*name* vocabulary: the names collide, the subjects
  do not, and neither is the quota model this package implements.
- **No plan writer, no provenance, no work order.** This package produces `SelectionResult`
  values. Writing `plan.json`, recording provenance, and persisting a work order are Layer 4.
  `SelectionPolicy.write` is the single exception: it writes a policy document atomically via
  `infra.storage.atomic.atomic_write_json`.
- **The report is a plain dict, not a typed record.** `SelectionResult.report` has no schema and
  no version field, so a caller reading `underfilled_floors` is depending on an undocumented key.
