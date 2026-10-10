# document_acquisition

Layer 4 pipeline contract foundation for S9 accession-document acquisition.

## Purpose

Projects published S6 target plans into bounded S9 work orders, acquires SEC target bodies within configured byte limits, and owns append-only run-state and fixture evidence. Processing, review, and snapshot publication remain separate stages.

The CLI implements project, status, run, and fixture tracks. Capture and replay require explicit confirmation; live SEC access has a separate confirmation. Bundle and lazy-index response retention is opt-in through `--retain-response-evidence`.

## Contracts

- **Pinned selection policy**: Catalog-direct selection is exactly `submitted_primary` or `exact_form_with_lazy_index`; S9 cannot replace or upgrade it.
- **Distinct evidence**: Processing role, requested type, expected statutory type, index designation, physical sequence, and observed body type remain separate facts.
- **Finite response limit**: Run and fixture capture resolve `acquisition.max_response_bytes` through the shared settings registry; an explicit command-line value overrides configuration, and no unbounded sentinel is accepted.
- **Catalog-direct bundle identity**: With the exact-form selector, extracted primary SGML `<TYPE>` is compared to the pinned form as ASCII; mismatch or unverifiable type enters lazy-index recovery. Other selectors do not screen the submitted primary.
- **Transient ownership**: Acquired bodies remain under the shared transient root; receipts do not authorize cleanup, and publication/discard cleanup is not implemented.
- **Payload boundary**: Future snapshot payloads use separate binary and text Parquet relations; this package does not introduce an external CAS or durable payload directory.

## Deliberate gaps

- **No family-aware identity screen**: The catalog-direct exact-form selector records direct-body evidence as unverifiable and uses lazy-index lookup; text evidence cannot override the pinned target form or exact index `document_type`.
- **Bounded fixture evidence**: Direct successful bodies and bodyless failures can be captured without response retention. Bundle-source and lazy-index capture requires opt-in run-level response retention and is refused when complete evidence is unavailable; replay writes verified selected bytes only to a new caller-selected path.
- **No processing or publication**: S10 processing and S11 Parquet/DAG publication remain absent; S11 requires representative S9/S10 evidence and explicit approval.
- **No S7d review builder**: S10 processor outputs/fingerprints and cross-run content review contracts are not implemented, so review build/compare remain placeholders rather than fabricated reports.
- **No snapshot reader**: Acquisition snapshot relations and a published acquisition DAG do not exist; snapshot status/audit are gate-aware placeholders, not queries against S5/S6 or legacy storage.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `fixture` | manage S9 response fixtures | — |
| `process` | process acquired target bodies | `--run-id`, `[--workers]`, `[--artifacts]`, `[--json]` |
| `project` | project a published S6 target plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `publish` | publish an approved S11 snapshot | `--run-id`, `[--branch]`, `[--expected-branch-tip]`, `[--artifacts]`, `[--json]` |
| `review` | build and compare review artifacts | — |
| `run` | acquire pending S9 target bodies | `--run-id`, `[--retry-failures]`, `[--retain-response-evidence]`, `[--workers]`, `[--max-response-bytes]`, `[--confirm-stale-lock]`, `[--artifacts]`, `[--json]` |
| `snapshot` | inspect S11 status and evidence | — |
| `status` | inspect resumable acquisition runs | `[--run-id]`, `[--target-id]`, `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
python run.py acquisition --help
python run.py acquisition project --help
python run.py acquisition run --help
python run.py acquisition fixture create --fixture-id local-review
python run.py acquisition fixture capture --help
python run.py acquisition fixture list --fixture-id local-review
python run.py acquisition fixture replay --fixture-id local-review --capture-id CAPTURE --target-id TARGET --output ./replayed-body.bin
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

Review, processing, and snapshot command tracks remain unimplemented or gated. Fixture capture and replay do not initiate SEC requests or publish S11 artifacts.
