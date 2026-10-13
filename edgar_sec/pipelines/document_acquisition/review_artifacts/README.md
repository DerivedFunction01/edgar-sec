# document_acquisition review_artifacts

Layer 4 review-run generation from captured S9 cases and transient S10 results.

## Purpose

The builder materializes and verifies captured fixture evidence internally, validates
the matching run and work-order pins, and reuses its S10 result to write content-pinned
review records in the shared review-run layout. It does not consume the body a second
time or rerun processing. Runs remain diagnostic artifacts and do not publish
acquisition snapshots.

## Contracts

- **Offline input**: Review generation reads fixture records and existing run state; it
  never initiates SEC requests.
- **Pinned cases**: Each manifest row identifies its fixture, capture, target, source
  digests, processing profile, receipt, and generated artifact digest.
- **No raw export**: Review generation writes review artifacts, not a caller-selected
  copy of the fixture body.
- **Stable comparison**: Case identifiers and manifest order are deterministic for the
  selected fixtures; the shared review console compares case artifacts.
- **No publication**: Review outputs are not S9/S11 result schemas or publisher input.

## Usage examples

```bash
python run.py acquisition review generate --fixture FIXTURE --capture-id CAPTURE --target-id TARGET
python run.py acquisition review compare --base REVIEW_A --new REVIEW_B
```

## Artifact layout

```text
{review_run}/
├── cases/{accession}--{fixture_capture_digest}/
│   └── processing-review.json
└── manifest.jsonl
```

## Deliberate gaps

- **Retained-run requirement**: Cases whose source run body is no longer available are
  reported as execution errors; reconstructing a new acquisition run from fixture data
  remains separate work.
- **Partial processors**: Raw identity and pinned TEXT passthrough are available; other
  transforms remain explicit unsupported or not-evaluated outcomes.
