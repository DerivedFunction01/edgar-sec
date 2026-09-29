# Phase 2 Expansion Guards and Partition Retirement

> [!IMPORTANT]
> **Status:** IMPLEMENTED. Source, tests, and the corrected contract/parity
> records below were changed in one pass; `check.py` is the gate.
> **Trigger:** an independent review of the implemented
> [phase_2_closure.md](phase_2_closure.md) found that `filing_catalog expand`
> accepted parent plans it could not legitimately extend, and that the generic
> `runtime.partition_count` setting was still registered with no consumer.
> **Relationship to the prior closure plan.** `phase_2_closure.md` §2.3 required
> selection-fingerprint verification in expansion and forbade fallback
> recomputation. That requirement was **not met**: the fingerprint was
> recomputed when absent, and two `None` allowances were left in place. The rest
> of the prior plan's scope was implemented. This document records the
> remediation and the partition retirement; it does not reopen the settled
> decisions in that plan.

## What was wrong

Expansion is handed a directory (`--parent <path>`), not resolved from a plan
id, so it gets none of the protection that plan identity gives an ordinary
lookup. A bundle published under an older schema has a different `plan_id` and
lives elsewhere, but nothing stopped an operator pointing `--parent` straight at
it. Four defects followed from the single missing gate.

1. **No schema check at all.** `plan_schema_version` was written into every
   `plan.json` and folded into plan identity, but nothing ever compared it.
2. **The `None` allowance admitted old plans.** `validate_parent` accepted
   `parent_meta.get("seed_fingerprint") not in (None, seed_fingerprint)`. A
   missing key yields `None`, which the tuple whitelists — so a plan that lacked
   a seed fingerprint passed the "parent and child use the same seed CIK set"
   check. `policy_corpus` had the same shape. Both fields are written
   unconditionally by the current planner, so a missing value can only mean a
   different schema or a malformed bundle.
3. **The fingerprint was recomputed, not verified.** `prepare_parent` fell back
   to `plan_fingerprint(parent_meta, parent_keys)` when the stored value was
   absent, re-stamping a parent with whatever its locators now were.
4. **The failure was undiagnosable.** The seed sidecar was read before any
   version check, and `read_seed_filers_csv` raises a bare `FileNotFoundError`,
   so a 1.0 bundle reported as a missing file rather than as the schema mismatch
   it was. A raw `FileNotFoundError` is the correct exception for a missing
   file; it is the wrong one here, where the operator did not mis-type a path.

Reproduced against real published plans before the fix: a 1.0 partial downgrade
was **silently accepted** and a child plan published; the same downgrade with
`seed_fillers.csv` deleted leaked a raw `FileNotFoundError`. Both are now
`ParentPlanError` with a republish instruction, and neither publishes a child.

## What changed

- `validate_parent_schema()` is a new gate comparing the parent's
  `plan_schema_version` against `TARGET_PLAN_SCHEMA_VERSION`, then requiring
  `plan_id`, `catalog_id`, `policy_corpus`, `seed_fingerprint`, and
  `plan_fingerprint`. It runs in `expand()` immediately after reading
  `plan.json` and **before** the sidecar read, and again in `prepare_parent()`
  so that public entry point is not a way around it.
- The `None` allowances in `validate_parent` are removed; both fields are now
  compared directly.
- `prepare_parent` recomputes the fingerprint from the parent's locator keys and
  requires an exact match, raising when the bundle was modified after
  publication. The recompute fallback is gone.
- `_read_parent_seed_filers` translates `FileNotFoundError` and `ValueError`
  from the sidecar reader into a `ParentPlanError` naming the file and the
  incomplete bundle, since the schema gate has already run by then.
- 14 regression tests in `tests/pipelines/filing_catalog/test_expansion.py`:
  both reported probes, parametrised version rejection (absent, older, newer,
  empty), parametrised required-field rejection, a tampered fingerprint, missing
  and malformed sidecars, and the `prepare_parent` entry point. Each asserts no
  child plan directory is created. The test helper that read
  `parent_meta.get("seed_fingerprint", "")` — the same tolerance, in the tests —
  now reads the field directly.

## Deferral — Phase 2.5 distribution

Operational partitioning is **not** a Phase 1 or Phase 2 concern in v2, and the
setting that implied it is retired rather than parked.

- v1's Phase 1 split CIKs into operational partitions by modulo, stored
  `partition_count` and partition manifests, and accepted `--partition-id`. v2
  replaced this: `Plan` fixes chunk membership by roster ordinal and
  `chunk_size`, and `assignment.divide_chunks(chunk_count, worker_count)`
  produces a separate, content-addressed chunk-to-worker assignment. Reassigning
  machines changes an assignment, not a plan, so no checkpoint is orphaned.
- v1's Phase 2.5 did consume `partition_count`, for locator distribution and for
  handoff coverage validation. That is real prior art, not a reason to retain a
  dead setting: v2's Phase 2.5 has not chosen its distribution unit yet.
- v2 Phase 2's `targets/form=<form>/` are **storage** partitions. No operator
  selects among them and no worker is assigned one.

So `runtime.partition_count`, `RuntimeSettings.default_partition_count`, and
`DEFAULT_PARTITION_COUNT` are removed, with a test that fails if any returns.

**The open question for Phase 2.5** is deliberately left open rather than
pre-answered by a foundation default:

- What is the distribution unit — locators, documents, or worker chunks?
- Is distribution a static assignment artifact, as in Phase 1, or fixed partition
  ids that a worker claims by number?
- If fixed partition ids survive, what is the handoff identity and schema, and
  what validates coverage (v1 required the set to be exactly `1..partition_count`
  with no duplicates)?
- What does the coordinator merge, and what is its scope: per run or cross run?

If that design needs a count, it registers a phase-owned setting with its own
settings provider at that time. A dormant foundation-level default is not the
place to keep it, because an operator who sets an advertised env var reasonably
expects it to change behaviour, and this one did not.

## Corrected records

The audit also surfaced false claims in the binding contract and in the parity
records. Each was verified against the code before correction.

- **`AGENTS.md` §4.1** claimed `plan` divides work into "fixed-size chunks …
  and operational partitions". v2 has no operational partitions. It now
  describes chunking plus static chunk-to-worker assignment, and states that
  assignment and worker count are excluded from plan identity by construction.
  §4.3's merge contract is corrected the same way: null and duplicate CIKs are
  rejected, while duplicate accessions are reportable fan-out.
- **`phase_1.md`** gained a "Closure note" recording the retirement, and its
  audit-defect list no longer implies the modulo split is current.
- **`parity_inventory.csv`** row 435 claimed v2 `build_plan` "partitions by
  `chunk_index % partition_count`" and "asserts partition coverage". Neither
  exists; the row now describes the ordinal-range plan and `divide_chunks`, and
  records the modulo mechanism as a deliberate retirement.
- **`gap_register.md` §4.1** is closed, and **§4.3** is corrected. The §4.3 claim
  that `validate_chunks` performs two checks was wrong: validation is split
  across `validate_chunks` (coverage, foreign/missing chunks, schema, row count,
  CIK coverage and uniqueness) and `merge_chunks` (null and duplicate CIKs, final
  row count and schema), and the cited line range no longer pointed at
  validation code. The one genuine divergence from v1 is that duplicate accessions
  warn rather than fail, which is deliberate.
- **`foundation/runtime/settings/README.md`** drops the setting row, the
  `RuntimeSettings` field, and the default constant, and records the retirement
  in its deliberate-gaps section.
- **`pipelines/README.md`** distinguishes the retained `chunk_size` from the
  retired `partition_count`.
- **`.kilo/plans/1790659380377-phase-1-parity-closure.md`** is superseded on its
  partition-specific instructions only: resolving `partition_count` at the
  options boundary, validating modulo partition coverage in `build_plan`, and
  wiring `cmd_run --partition` through `worker.run_partition`. Its unrelated Phase
  1 work is unaffected.

## Deliberate gaps

- **Published plans are not migrated.** A 1.0 bundle stays on disk and is
  refused with a republish instruction. There is no compatibility path, no
  upgrade, and no shim, per `AGENTS.md` §1.1.
- **`chunk_size` is untouched.** It remains a plan-defining input; only the
  unread setting was retired.
- **No Phase 1 merge behaviour changed.** The correction to §4.3 was
  documentary. Document-level fan-out validation belongs to Phase 2.5, whose
  output model does not exist yet.
