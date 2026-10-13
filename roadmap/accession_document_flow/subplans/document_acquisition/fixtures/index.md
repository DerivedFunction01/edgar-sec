# `acquisition fixture`

## Purpose and status

Retain exact S9 acquisition evidence for offline review. New fixtures pin one validated,
published S6 target plan by stable ID, schema version, and digest. There are no
pre-existing acquisition fixtures on disk; the rewritten store has no migration, old
schema reader, alias, or dual-version path. Direct responses and bodyless failed
attempts can be captured; bundle and lazy-index response groups require evidence retained
during acquisition with `--retain-response-evidence`.

## CLI and operator shape

```text
acquisition fixture create --fixture <id> --plan-id <published-s6-plan-id>
acquisition fixture fill --fixture <id> --run-id <run-id> --target-id <id> --attempt-id <id> [--max-response-bytes <positive-int>]
acquisition fixture list [--fixture <id>] [--capture-id <id>] [--target-id <id>]
acquisition review generate --fixture <id> [--capture-id <id>] [--target-id <id>]
acquisition review compare --base <review-dir> --new <review-dir>
acquisition review analyze --run <review-dir> [--output <analysis-path>]
```

The interactive fixture/review console selects a validated published S6 plan, keeps it
active for the session, and supports switching plans. Create uses that active plan. Fill
selects a fixture pinned to the active plan, requires exact run/target/attempt IDs, shows
the byte cap and evidence identity, and asks default-no consent only before retaining
local evidence. Fill validates that the recorded S9 run uses the same plan and current
attempt. Listing is deterministic, read-only, and reports plan pins, capture/case counts,
and case acquisition statuses. No replay/export command or menu action is provided.

## Capture contract

- Capture requires a positive response-byte cap and validates the fixture pin, run
  manifest/work order, target membership, exact recorded attempt, attempt kind/source,
  and recorded body evidence. It makes no SEC request.
- A successful direct-body attempt is captured from its verified retained response. A
  bodyless failed attempt is captured as metadata only. Bundle and lazy-index cases are
  captured only when the run retained every required response group member.
- Capture IDs are deterministic from run, target, and attempt identity. Capture and case
  records are immutable; conflicting evidence is refused.
- Response bodies are streamed into Zstandard-compressed SQLite BLOBs and verified
  before the atomic append. The configured cap applies to uncompressed response bytes.
- Capture accepts only the current unsuperseded attempt group; it is not a historical
  attempt selection API.

## Listing and internal body verification

Listing opens fixtures read-only and performs SQLite integrity and foreign-key checks.
It does not decompress or hash response BLOBs. Review generation alone uses internal
body verification/materialization in temporary storage; it does not export fixture bytes
to a user-selected path or mutate fixture evidence.

## Review console

Review generation verifies the fixture-selected body and its acquisition run/pinned work
order, then processes the run's staged body using the pinned operations. It remains
offline and requires the source run and staged body to remain available. A review run
contains a `manifest.jsonl` and per-case `processing-review.json` artifacts. Comparison
validates both review runs before computing the shared case-level diff. Offline analysis
validates manifests and output digests, reports fixture-verification and processing
outcomes with deterministic per-run aggregates, and never accesses fixture BLOBs.
Analysis writes a separate report only when `--output` is supplied.

## Detailed contracts

- [Fill fixture cases](fill.md)
- [List fixture evidence](list.md)
- [SQLite schema and BLOB lifecycle](storage.md)
