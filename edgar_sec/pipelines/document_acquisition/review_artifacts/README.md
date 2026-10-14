# document_acquisition review_artifacts

Layer 4 parser-review generation from captured acquisition cases.

## Purpose

The builder materializes and verifies fixture bytes, then invokes the current
`AcquisitionProcessor` handlers directly. It does not need the source run's work order,
processing result, or receipt, and it never makes SEC requests. Runs are diagnostic
artifacts and do not publish acquisition snapshots.

## Contracts

- **Offline input**: Review generation parses verified fixture bytes and never initiates
  SEC requests or reads source-run processing outputs.
- **Pinned cases**: Each manifest row identifies its fixture, run capture, target, body
  digests, current handler results, and generated artifact digest.
- **Single parser path**: Current handlers process every acquired fixture case; target,
  capture, and attempt identifiers are not review filters.
- **Stable comparison**: Case identifiers and manifest order are deterministic for the
  selected fixtures; the shared review console compares case artifacts.
- **Digest scope**: Artifact and output digests detect inconsistency or accidental
  corruption, not malicious rewrites by someone who can also edit the manifest. A trusted
  signature or externally pinned digest is required for authenticity.
- **No publication**: Review outputs are not S9/S11 result schemas or publisher input.

## Usage examples

```bash
python run.py acquisition review generate --fixture FIXTURE
python run.py acquisition review compare --base REVIEW_A --new REVIEW_B
```

## Artifact layout

```text
{review_run}/
├── cases/{accession}--{fixture_capture_digest}/
│   ├── operations/
│   └── processing-review.json
└── manifest.jsonl
```

## Deliberate gaps

- **Unavailable bytes**: Fill cannot recover response bodies that the source acquisition
  run did not retain.
- **No production gates**: Parser review reports current handler behavior; it does not
  authorize production route budgets or publication.
