# `acquisition project`

## Purpose and status

Project a published S6 target-plan bundle into an immutable, resumable S9
acquisition run. The offline project service and CLI command are implemented; network
acquisition, processing, status inspection, and publication remain separate tracks.

The service validates an S6 bundle-v2 target plan, streams its rows into a Parquet
work order, seeds the run-scoped SQLite state from bounded batches, and atomically
publishes the complete transient run directory. It does not list plans interactively,
make SEC requests, process bodies, or publish an acquisition snapshot.

## CLI shape

```bash
python run.py acquisition project --plan-id <target-plan-id>
python run.py acquisition project --plan-id <target-plan-id> --json
python run.py acquisition project --plan-id <target-plan-id> --artifacts <path>
```

`--plan-id` selects one validated published target plan. `--artifacts` overrides the
resolved artifact root, and `--json` selects stable machine-readable output.

## Intended interactive UX (not implemented)

1. The operator lists published S6 target plans and shows each plan's ID, digest,
   catalog/inventory pins, target counts, and schema versions.
2. After selection, it validates the complete plan bundle and previews executable
   versus skipped target counts. Projection is local and does not prompt for SEC
   authorization.
3. It creates or reuses the deterministic run, then displays the run ID, work-order
   digest, and path. Invalid plans return to the menu without creating a run.

The CLI command receives the plan ID explicitly and prints the same summary; `--json`
is stable machine-readable output. `--artifacts` resolves through the shared paths
owner, never a command-specific path join.

## Service signatures

```python
def project_acquisition_run(
    target_plan_id: str,
    *,
    paths: AcquisitionPaths,
) -> ProjectedAcquisitionRun: ...

def cmd_project(args: argparse.Namespace) -> int: ...
```

`ProjectedAcquisitionRun` contains the run ID, immutable manifest, executable and
skipped counts, work-order digest, and `reused` flag. The service raises a typed
`AcquisitionProjectError` for corrupt input, unsafe paths/locators, unsupported
versions, or an existing run whose content differs. The CLI and operator call the
same service and never duplicate projection logic.

## Contract

- Validate the S6 manifest, target schema, declared target-part sizes and digests,
  and required source pins before creating a run. A null inventory pin is accepted
  only for the catalog-only primary plan contract.
- Accept bundle schema version `2`, matcher `target-matcher-v2`, and target relation
  schema version `1` only. Verify declared part paths, row counts, byte sizes,
  SHA-256 values, Arrow schemas, and manifest digest. Reject missing, extra,
  symlinked, or escaping target parts.
- Treat the S6 target bundle as self-contained. Do not reopen the filing-catalog
  plan or inventory snapshot and do not re-evaluate profile matching.
- Make only matched targets with supported `direct_url` or `bundle_sequence`
  retrieval executable. Preserve all other target outcomes as skipped work with a
  reason; they cause no SEC request.
- Preserve the target's plan ID/digest, target ID, request identity, accession,
  source origin, retrieval mode, locator or sequence, and pinned
  `catalog_direct_selection` in the work order. S9 cannot choose or upgrade the
  selector during projection.
- Import only the S6 owner `paths.py` and `schemas.py` contracts. Derive direct
  document paths from the validated URL; do not reinterpret `target_type` or reopen
  `inventory_entry_id` to guess a filename.
- Derive run identity from the validated plan identity and versioned acquisition
  work-order contract. Repeating projection for the same identity reuses a valid
  run; an existing invalid or conflicting run is refused, not overwritten.
- Keep `target_status` from S6 distinct from S9 acquisition outcomes. Projection
  does not fetch, capture fixtures, normalize, or publish payloads.

## Result and refusal behavior

Report run ID, target-plan ID and digest, executable/skipped target counts, work-order
digest, and whether an existing run was reused. Refuse malformed manifests, unsafe
locators, inconsistent provenance, unsupported target schema, or target parts that
are absent or fail integrity validation before any network operation.

## Acceptance

A run can be reconstructed from its pinned S6 plan and persisted work order alone.
The command makes no network requests and leaves the source target plan unchanged.
Repeat projection for identical source bytes reuses the validated run; corrupted or
divergent existing state fails closed.

Offline tests cover target-plan schema/version refusal, null inventory pins outside
the catalog-only primary case, missing/extra/path-escaping/tampered parts, a malformed
or duplicate target ID, unsafe cross-accession URLs, bool/non-positive sequences,
unsupported retrieval modes, and identical-versus-divergent existing run reuse.
