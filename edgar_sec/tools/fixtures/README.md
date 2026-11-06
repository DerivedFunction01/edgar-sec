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

## Deliberate gaps

- **No fixture filling**: Downloading for candidate scoring happens here;
  filling and publishing fixtures belongs to the document-acquisition pipeline,
  not this package.
