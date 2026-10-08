# Cohort CLI & Interactive Console Specification

This specification defines the Layer 4 user interface and orchestration package:
`edgar_sec.pipelines.cohort` (`cli.py`, `menu.py`, `options.py`).

Storage remains strictly in Layer 2 (`infra.storage.cohort`), ensuring full compliance with the repository downward-only layered architecture.

---

## 1. Interactive Menu Primitive: `MenuSeparator`

Added to `edgar_sec.foundation.runtime.interactive`:

```python
@dataclass(frozen=True, slots=True)
class MenuSeparator:
    """Non-selectable visual divider or section title in an interactive menu."""

    title: str = ""
```

### 1.1 Behavior & Dispatch Contracts
1. **Key Assignment (`assign_menu_keys`)**:
   - `MenuSeparator` instances pass through unmodified.
   - They do **not** consume keys from numeric or automatic key sequences.
2. **Rendering (`run_interactive_menu`)**:
   - Renders formatted dividers:
     ```text
     ── Section Title ──────────────────────────────────────────────
     ```
   - Renders a blank spacer line when `title == ""`.
3. **Dispatch**:
   - Separators are excluded from `action_map`; typing any key cannot activate a separator.

---

## 2. Cohort Management Console (`[c]`)

Accessible from `edgar-sec cohort console` or via `[c]` in `metadata_sync`:

```text
================================================================================
Cohort Management Console (Layer 4)
Catalog: .artifacts/cohorts/cohorts.sqlite  |  Cohorts: 6  |  Family Index: active
================================================================================
── Official Sources & Taxonomy ─────────────────────────────────────────────────
  1. Refresh & manage official sources (Universe & Tickers, swap active version)
  2. Assign company families for the universe

── Cohort Ingest & Algebra ──────────────────────────────────────────────────────
  3. Process file to cohort (CSV, TSV, TXT, Parquet)
  4. Cohort workspace (interactive session: bind, let, diff, peek, save, drop, clear)
  5. Sample cohort (Uniform random, Hash modulo, Family-stratified)

── Cohort Maintenance & Query ──────────────────────────────────────────────────
  6. Query CIKs or entity names (paginated in-cohort query or global find)
  7. Inspect cohort details (Provenance, counts, sample CIKs)
  8. Rename / Tag cohort
  9. Delete cohorts
  0. Back to caller menu

Choice [0]:
```

---

## 3. Short Hash Prefix Resolution & Identifier Lookups

All CLI commands accepting a `<cohort>` identifier (`query`, `info`, `rename`, `tag`, `delete`, `diff`, `sample`, etc.) resolve identifiers via `CohortCatalog.resolve_cohort_identifier`:

1. **Minimum Length Requirement**:
   - Minimum **7 characters** (excluding optional `c-` prefix; e.g. `59508de` or `c-59508de`).
   - If input is shorter than 7 hex characters and does not match a human name, fails immediately:
     `Error: Ambiguous or short hash prefix '5950'. Hash lookups require at least 7 characters.`
2. **Resolution Precedence**:
   1. **Exact Name Match**: `SELECT * FROM cohorts WHERE name = ?`
   2. **Exact ID Match**: `SELECT * FROM cohorts WHERE cohort_id = ?`
   3. **Prefix Match** (when $\ge 7$ chars and valid hex):
      `SELECT * FROM cohorts WHERE cohort_id LIKE 'c-' || ? || '%' OR cohort_id LIKE ? || '%'`
3. **Ambiguity & Missing Refusal**:
   - If prefix matches $> 1$ cohort: Fails with exit code 1, listing candidate IDs:
     `Error: Ambiguous cohort prefix '59508de'. Matches 2 cohorts: [c-59508de7a1b2, c-59508def098c]. Provide more characters.`
   - If prefix matches 0 cohorts: Fails with `Error: Cohort not found: '<identifier>'`.

---

## 4. Unified CLI Grammar

Implemented in `edgar_sec.pipelines.cohort.cli`:

```bash
# --- Ingestion & Intake ---
edgar-sec cohort import --input uploads/tech_firms.txt --name tech_firms --tags tech,q3
edgar-sec cohort import --input uploads/sec_ciks.csv --name sec_ciks --delimiter ","
edgar-sec cohort import --input uploads/raw_list.txt                      # returns c-59508de79eafa64e

# --- Catalog Maintenance & Inspection ---
edgar-sec cohort list [--tag tech] [--pinned-only] [--search apple] [--limit 50] [--offset 0]
edgar-sec cohort info tech_firms                                         # prints counts, schema, provenance
edgar-sec cohort rename 59508de --name tech_group                        # 7-char prefix match
edgar-sec cohort tag 59508de --add benchmark,active --remove draft
edgar-sec cohort delete 59508de [--keep-dataset]                         # refuses if pinned or active source

# --- Query & Search (with Pagination) ---
edgar-sec cohort query tech_firms --name "Apple" --limit 10 --offset 0
edgar-sec cohort query tech_firms --cik 0000320193
edgar-sec cohort find --cik 0000320193 --limit 25 --page 1
edgar-sec cohort find --name "Energy" --limit 20

# --- Composable Sampling ---
edgar-sec cohort sample \
    --source universe --method modulo --rate 5 --group-family --name universe_sample_5pct
edgar-sec cohort sample \
    --source universe --method random --limit 1000 --seed 42 --name universe_sample_1k

# --- Session Initialization & Context Switching ---
edgar-sec cohort workspace init q3_rebalance             # create session & set as active context
edgar-sec cohort workspace current                       # print active session and variable count
edgar-sec cohort workspace sessions                      # list all existing sessions
edgar-sec cohort workspace use default                   # switch active session context

# --- Stateful Workspace Commands (Powered by ObjectStore) ---
edgar-sec cohort workspace bind A tech_giants_q3 [--session q3_rebalance]
edgar-sec cohort workspace bind B curated_ciks
edgar-sec cohort workspace let x "A + B"
edgar-sec cohort workspace let y "C - D"
edgar-sec cohort workspace let z "x - y"
edgar-sec cohort workspace diff z B
edgar-sec cohort workspace peek z --limit 10
edgar-sec cohort workspace save z --name merged_final --tags q3,merged

# Variable lifecycle & session cleanup
edgar-sec cohort workspace list [--session <id>]
edgar-sec cohort workspace drop x [--session <id>]
edgar-sec cohort workspace clear [--session <id>]
edgar-sec cohort workspace clean [--older-than 24h]      # prune expired sessions across catalog

# --- Stateless Chained Operations & Expressions ---
edgar-sec cohort merge --expr "(tech_firms + curated_ciks) - unindexed_active" --name merged_tech
edgar-sec cohort merge --expr "(A + B) - C" --serialize  # dry-run AST preview (--name is optional)

# --- Interactive Console ---
edgar-sec cohort console
```

---

## 5. Entrypoint Registration (`run.py`)

Hooked into repository launcher:
```python
LauncherEntry(
    id="cohort",
    label="Cohort Management",
    description="Manage, import, query, and combine registrant cohorts",
    module="edgar_sec.pipelines.cohort.cli",
)
```
