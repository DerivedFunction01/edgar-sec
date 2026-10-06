# S12 — Operator Integration and End-to-End Quality Gate

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S12**.
- Status: integration and gate stage; small CLI surface plus the full verification
  suite.
- Depends on: S0–S11; it is the last stage to receive the other subplans' outputs.
- Non-blocking: nothing in this flow.

## Objective

Integrate the operator surface, publish machine-readable summaries, and verify the
complete pipeline end to end from a fixture cohort to independent target plans plus
review. The interactive operator is a later UX decision; the initial surface is
explicit-artifact oriented.

## CLI surface

Commands are staged by capability; only the following land in the initial release:

```text
inventory fill --catalog-plan <id> --fixture <id>   # S2 capture
inventory build --catalog-plan <id>                 # S5 publication
inventory query --snapshot current --accession <acc>
inventory query --snapshot current --form <form> [--source-cik <cik>]
inventory inspect --snapshot <id>                   # S7
inventory review-artifacts --fixture <id> --output <dir>
inventory review --base <dir> --new <dir>
documents plan --inventory <snapshot|current> --profile <path>   # S6
```

`index.json` parsing, a broader `status` command, acquisition/processing CLI commands,
and the interactive wizard are added only in their owning subplans. No query command
fetches index pages or filing bodies; only `inventory build` fetches index pages for
accessions missing from the selected base snapshot.

## Machine-readable summary

A summary records `fresh`/`reused` snapshot status and counts for:

- input
- indexed
- matched
- not-filed
- required-missing
- constructed-candidate
- ambiguous
- unresolved
- failed

Counts are stable, typed, and machine-parseable; they are the single source of truth
for run reports.

## Verification suite

Run, in order:

1. Mirrored offline tests under `tests/`, matching the source tree.
2. Scanner and layer checks via the policy scanners (layer-boundary,
   resource-allocation, whole-file-read, legacy-shims, prose-length, etc.).
3. CLI refusal semantics: unknown flags, bad snapshots, missing fixtures, and empty
   selections are rejected.
4. Broker lifecycle: one broker per run, no worker-side clients, rate limiting.
5. No document payload persistence: verification that no payload bytes or linkage
   appear in inventory or target-plan artifacts.
6. A tiny vertical run from a fixture cohort to two independent target plans plus
   review:
   - `inventory build` from a fixture cohort,
   - two `documents plan` runs with different profiles against the same snapshot,
   - an index review comparing two parser versions,
   - a target-plan comparison.

## Test gates

- Tests are offline, deterministic, and fast; the full suite must pass before a
  release.
- Targeted tests run against changed files; the full suite runs only when explicitly
  requested.
- No hardcoded resource counts; worker sizing derives from `derive_resources`.
- No `document_storage` pipeline imports.
- The `check.py` gate is the canonical entry point: `check.py --fast` for the
  standard gate, `check.py --all` only when explicitly requested.

## Documentation updates

Update the following when public packages and commands land:

- package READMEs in the owning layers,
- layer layout tables,
- the root `README.md`,
- and this roadmap.

## Acceptance criteria

The operator surface is small and artifact-oriented, summaries are machine-readable
with typed counts and fresh/reused status, the full verification suite passes, the
vertical fixture-to-plan-to-review run succeeds, and documentation is updated to
reflect the public surface. The interactive operator is explicitly deferred.
