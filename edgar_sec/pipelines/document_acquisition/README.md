# document_acquisition

Layer 4 pipeline contract foundation for S9 accession-document acquisition.

## Purpose

Projects published S6 target plans into bounded S9 work orders, acquires SEC target bodies within configured byte limits, and owns append-only run-state and fixture evidence. Processing, review, and snapshot publication remain separate stages.

The CLI implements project, status, run, and fixture tracks. Capture and replay require explicit confirmation; live SEC access has a separate confirmation. Bundle and lazy-index response retention is opt-in through `--retain-response-evidence`.

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
- **Transient ownership**: Acquired bodies remain under the shared transient root; receipts do not authorize cleanup, and publication/discard cleanup is not implemented.
- **Payload boundary**: Future snapshot payloads use separate binary and text Parquet relations; this package does not introduce an external CAS or durable payload directory.

## Deliberate gaps

- **No family-aware identity screen**: The catalog-direct exact-form selector records direct-body evidence as unverifiable and uses lazy-index lookup; text evidence cannot override the pinned target form or exact index `document_type`.
- **Bounded fixture evidence**: Direct successful bodies and bodyless failures can be captured without response retention. Bundle-source and lazy-index capture requires opt-in run-level response retention and is refused when complete evidence is unavailable; replay writes verified selected bytes only to a new caller-selected path.
- **Partial S10 worker**: `process_target` validates one explicit request, enforces form-family operation permissions, supports raw identity and pinned text-route byte identity, and records the S9 receipt. Other transforms remain explicit unsupported outcomes; bundle-child route identity and a run coordinator remain unavailable.
- **Transient terminal projection**: `result_projection.project_terminal_results` consumes request/result iterables, joins them with the work order in temporary disk-backed SQLite, verifies staged references, and exposes a closeable target iterator with a deterministic fingerprint. Its spool is not a persisted S10/S11 result or snapshot.
- **Fixture review boundary**: `review generate` replays captured evidence and writes shared-layout processing review records for retained S9 runs. Cases requiring an unavailable transform or missing retained run body are recorded as failures; review records are not persisted S9/S11 results.
- **No publication**: S11 Parquet/DAG publication remains absent and requires representative S9/S10 evidence and explicit approval.
- **No full transform review**: Review generation currently exercises raw identity and pinned TEXT passthrough; reviewer labels, non-identity renderers, and exhibit assessment remain future work.
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
| `fixture` | manage S9 response fixtures (`create`, `fill`, `list`, `replay`) | — |
| `process` | process acquired target bodies | `--run-id`, `[--workers]`, `[--artifacts]`, `[--json]` |
| `project` | project a published S6 target plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `publish` | publish an approved S11 snapshot | `--run-id`, `[--branch]`, `[--expected-branch-tip]`, `[--artifacts]`, `[--json]` |
| `review` | generate and compare fixture-backed review artifacts (`generate`, `compare`) | — |
| `run` | acquire pending S9 target bodies | `--run-id`, `[--retry-failures]`, `[--retain-response-evidence]`, `[--workers]`, `[--max-response-bytes]`, `[--confirm-stale-lock]`, `[--artifacts]`, `[--json]` |
| `snapshot` | inspect S11 status and evidence | — |
| `status` | inspect resumable acquisition runs | `[--run-id]`, `[--target-id]`, `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
python run.py acquisition --help
python run.py acquisition project --help
python run.py acquisition run --help
python run.py acquisition fixture create --fixture local-review
python run.py acquisition fixture fill --fixture local-review --run-id RUN --target-id TARGET --attempt-id ATTEMPT
python run.py acquisition fixture list --fixture local-review
python run.py acquisition fixture replay --fixture local-review --capture-id CAPTURE --target-id TARGET --output ./replayed-body.bin
python run.py acquisition review generate --fixture local-review --capture-id CAPTURE --target-id TARGET
python run.py acquisition review compare --base ./review-runs/run-BASE --new ./review-runs/run-NEW
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
│   │   └── {review_id}/
│   │       ├── cases/
│   │       │   └── {accession}--{case_digest}/
│   │       │       └── processing-review.json
│   │       └── manifest.jsonl
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

Run-level processing orchestration and snapshot publication remain unimplemented or gated. Review generation uses retained S9 run artifacts and fixture evidence; per-target processing, fixture replay, review generation, and review comparison perform no HTTP requests or publish S11 artifacts.
