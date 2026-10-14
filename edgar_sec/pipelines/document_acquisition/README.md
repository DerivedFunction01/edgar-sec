# document_acquisition

Layer 4 pipeline contract foundation for S9 accession-document acquisition.

## Purpose

Projects published S6 target plans into bounded S9 work orders and owns append-only run state and fixture evidence. Each resumable run acquires eligible targets and then processes acquired targets under the same run lock; review and snapshot publication remain separate.

The CLI implements project, status, combined run/process, and fixture/review tracks. The
fixture/review console selects a validated published S6 plan for fixture creation; fills
retain only evidence from an exact recorded S9 run, target, and attempt. Bundle and
lazy-index response retention is opt-in through `--retain-response-evidence`.

## Contracts

- **Pinned selection policy**: Catalog-direct selection is exactly `submitted_primary` or `exact_form_with_lazy_index`; S9 cannot replace or upgrade it.
- **Pinned retrieval mode**: S9 executes the source and sequence selected by S6.
  It does not compare advertised sizes, group targets into a shared bundle fetch,
  or fall back from an ordinary failed direct request to the accession bundle.
  S6 treats only the exact observed primary filenames `0000.txt`, `0000.htm`,
  `0001.txt`, and `0001.htm` as placeholder signals, independent of form/date;
  nested paths and arbitrary suffix matches are excluded. It selects the bundle route
  only with an observed positive sequence and pinned bundle URL. Catalog-only targets
  without those facts remain unresolved. Accession-qualifying a catalog child URL is
  not retrieval authorization; S9 executes only the mode pinned by S6.
- **Distinct evidence**: Processing role, requested type, expected statutory type, index designation, physical sequence, and observed body type remain separate facts.
- **Finite response limit**: Run and fixture capture resolve `acquisition.max_response_bytes` through the shared settings registry; an explicit command-line value overrides configuration, and no unbounded sentinel is accepted.
- **Catalog-direct bundle identity**: With the exact-form selector, extracted primary SGML `<TYPE>` is compared to the pinned form as ASCII; mismatch or unverifiable type enters lazy-index recovery. Other selectors do not screen the submitted primary.
- **Processing boundary**: Engine owns SGML type screening and resolves operation capability/handler pins from path facts; pipeline code owns source selection, the pinned operation contract, and staged outputs. SGML child filenames use content routes even when their names contain slashes.
- **Transient ownership**: Acquired bodies remain under the shared transient root; receipts do not authorize cleanup, and publication/discard cleanup is not implemented.
- **Payload boundary**: Future snapshot payloads use separate binary and text Parquet relations; this package does not introduce an external CAS or durable payload directory.

## Deliberate gaps

- **No family-aware identity screen**: The catalog-direct exact-form selector records direct-body evidence as unverifiable and uses lazy-index lookup; text evidence cannot override the pinned target form or exact index `document_type`.
- **Bounded fixture evidence**: Direct successful bodies and bodyless failures can be captured without response retention. Bundle-source and lazy-index capture requires opt-in run-level response retention and is refused when complete evidence is unavailable. Fixtures are immutable to their published S6 plan pin.
- **Limited S10 transforms**: `process_target` validates one explicit request, passes authoritative SGML/archive path facts to Engine, supports raw identity and pinned text normalization, and records the S9 receipt. XML conversion remains an explicit unsupported outcome until its handler is registered.
- **Transient terminal projection**: `review_artifacts.result_projection.project_terminal_results` consumes request/result iterables, joins them with the work order in temporary disk-backed SQLite, verifies staged references, and exposes a closeable target iterator with a deterministic fingerprint. Its spool is not a persisted S10/S11 result or snapshot.
- **Fixture review boundary**: `review generate` verifies fixture bodies and their pinned S6/S9 work-order identity, then processes the retained S9 staged body through the work order's operation pins. It writes shared-layout review records offline; missing retained run bodies and unavailable transforms are recorded as failures. Review records are not persisted S9/S11 results.
- **Offline review analysis**: `review analyze` validates manifest, per-case artifact, and label sidecar digests before summarizing operation outcomes and label errors. `review holdout` requires an explicit issuer/time partition. Neither command fetches SEC data or mutates acquisition runs.
- **Frozen holdout partition**: `review holdout` requires a versioned JSON spec with an explicit accession century, training cutoff, non-overlapping holdout year range, and sorted issuer CIK roster. The report rejects repeated selected-body digests; near-duplicate review is not performed.
- **No publication**: S11 Parquet/DAG publication remains absent and requires representative S9/S10 evidence and explicit approval.
- **Diagnostic exhibit review only**: Eligible planned-exhibit TEXT results can carry a version-pinned, non-authoritative opening-view assessment into result and review artifacts. `review label` writes immutable human-label sidecars; `review analyze` reports per-form/family counts. This does not establish accuracy, enable a production transform, or activate a family.
- **No representative holdout**: `review holdout` requires a frozen issuer/time partition and independent labels. Current evidence has no representative labeled corpus; the report marks near-duplicate review as not performed and cannot approve family activation.
- **No snapshot reader**: Acquisition snapshot relations and a published acquisition DAG do not exist; snapshot status/audit are gate-aware placeholders, not queries against S5/S6 or legacy storage.
- **No cost-based selection or bundle grouping**: Child, complete-submission, and
  S1-reported sizes remain distinct evidence and do not select transport. A
  size-aware direct-versus-bundle optimizer and multi-target bundle reuse are
  deferred.
- **No authorized XBRL ZIP execution or asset filtering**: A constructed ZIP
  candidate is not authorization to fetch/unzip it. Availability and selection of
  assets inside a complete-submission text file also lack a policy.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `fixture` | manage S9 response fixtures | — |
| `project` | project a published S6 target plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `publish` | publish an approved S11 snapshot | `--run-id`, `[--branch]`, `[--expected-branch-tip]`, `[--artifacts]`, `[--json]` |
| `review` | generate, label, and evaluate offline review runs | — |
| `run` | acquire pending S9 target bodies | `--run-id`, `[--retry-failures]`, `[--retain-response-evidence]`, `[--workers]`, `[--max-response-bytes]`, `[--confirm-stale-lock]`, `[--artifacts]`, `[--json]` |
| `snapshot` | inspect S11 snapshot status | — |
| `status` | inspect resumable acquisition runs | `[--run-id]`, `[--target-id]`, `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
python run.py acquisition --help
python run.py acquisition project --help
python run.py acquisition run --help
python run.py acquisition fixture create --fixture local-review --plan-id PLAN_ID
python run.py acquisition fixture fill --fixture local-review --run-id RUN --target-id TARGET --attempt-id ATTEMPT
python run.py acquisition fixture list --fixture local-review
python run.py acquisition review generate --fixture local-review --capture-id CAPTURE --target-id TARGET
python run.py acquisition review compare --base ./review-runs/run-BASE --new ./review-runs/run-NEW
python run.py acquisition review analyze --run ./review-runs/run-NEW
python run.py acquisition review label --artifact ./review-runs/run-NEW/cases/CASE/processing-review.json --outcome positive --observed-kind exhibit --observed-authority reg_s_k_item_601 --observed-code 3.1 --annotator-id REVIEWER --annotated-at-utc 2026-10-13T20:00:00Z --evidence-ref normalized-text:chars-0-43
python run.py acquisition review holdout --run ./review-runs/run-NEW --spec ./holdout-spec.json
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── document_acquisition/
│   ├── fixtures/
│   │   └── {fixture_id}/
│   │       ├── fixture.sqlite
│   │       └── manifest.json
│   ├── review-runs/
│   └── snapshots/
│       └── {snapshot_id}/
├── document_planning/
│   └── plans/
│       └── {plan_id}/
├── runtime/
└── transient/
    └── document_acquisition/
        └── {run_id}/
            ├── handoff/
            │   └── receipts/
            │       └── {target_id}/
            │           └── {selected_sha256}.json
            ├── staging/
            ├── work_order/
            ├── cancelled.json
            ├── run.lock
            ├── run_manifest.json
            └── state.sqlite
```
<!-- AUTOGEN:PATHS:END -->

The run reports acquisition and processing outcomes together. Review generation uses
retained S9 run artifacts and fixture evidence; per-target processing, internal fixture
body verification, review generation, comparison, and analysis make no HTTP requests or
publish S11 artifacts. Fixture bodies are materialized only in temporary storage for
review verification.
