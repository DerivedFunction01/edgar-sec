# fixtures

Layer 6. Fixture-gathering planning and candidate scoring.

## Purpose

Plan fixture gathering from the filing catalog before any network work runs.
Screens filter the catalog to a candidate population; the plan samples,
shards, and prices it, and candidates are scored for tagged content.

## Contracts

- **Plan before network**: Sampling, sharding, and pricing complete before
  any download or fetch runs.
- **Substantial-content registry**: Only filings meeting the content floor
  enter the candidate registry; picks re-threshold from checkpoints.
- **Offline planning**: Plan generation performs zero network I/O.
- **Two-file transfer unit**: A fixture is `fixture.sqlite` + `manifest.json`;
  both files travel on every transfer, and a directory holding only
  `fixture.sqlite` cannot be opened.
- **Open validates the pin**: `open_fixture` requires the manifest beside the
  DB and cross-validates its plan pin against the DB's `fixture_meta`.
- **`--forms` does not scope policy selection**: `filing-catalog plan --scope
  policy --auto-policy` selection is not scoped by `--forms`.
- **Per-family policy documents**: Family fixtures use a scoped per-family
  policy document (precedents: `form144-htm-v1`, `form15-htm-v1`).
- **Captured fixtures re-fetch by manifest**: `fixture_cache` populates the
  untracked captured-fixture cache from
  `tests/fixtures/captured_manifest.json`; full-form rows verify against
  the manifest sha256, live-form rows fetch only as the dynamic-proof diff.

## Deliberate gaps

- **No fixture filling**: Downloading for candidate scoring happens here;
  filling and publishing fixtures belongs to the document-acquisition pipeline,
  not this package.
