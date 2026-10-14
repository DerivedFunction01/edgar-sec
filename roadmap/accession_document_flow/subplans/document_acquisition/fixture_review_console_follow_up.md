# Acquisition Fixtures & Review Console Follow-up

**Status: implemented.** The acquisition fixture/review console uses the shared inventory-style menu and a parser-body fixture contract. Its current behavior is evidenced by the acquisition operator, fixture store, review builder, and mirrored tests.

## Behavior

The menu exposes create, plan-driven fill, deterministic list, parser review generation, compare, offline analyze, `s` to switch the active S6 plan, and exit. Fixture selections are discovered and paginated. Fill asks for a target limit and explicit SEC-network consent, then fetches uncaptured executable targets from the fixture's pinned plan without creating or requiring an acquisition run.

The schema-v3 fixture is pinned to the published S6 plan and stores selected document bytes plus parser metadata. It stores a lazy-index page only when exact-form lazy resolution needs one and reuses that page for later targets for the accession. It does not retain ordinary HTTP responses, bundle containers, failed attempts, or S10 results. Earlier fixture-store schemas are rejected; there is no migration or dual-version reader.

Review generation verifies fixture bytes and referenced lazy-index evidence, then invokes the current acquisition-engine handlers offline. It does not require an acquisition run, processing result, or receipt. It writes a manifest and versioned per-case parser artifacts/outputs. Compare and analyze validate those artifacts without accessing fixture bodies or making network requests. Review output is diagnostic and does not publish snapshots.

## Contracts

- **Active plan**: Plan discovery returns validated published S6 plans. The selected plan is session-local; switching it never changes an existing fixture.
- **Plan-pinned fixture**: Create pins plan ID, digest, and schema version. Fill refuses a changed published plan.
- **Plan-scoped fill**: Capture identity groups selected bodies from one fill. Repeated fill skips stored target IDs and can continue with later targets.
- **Selected body and lazy evidence**: Fixture bytes are the selected parser input; only a lazy index required for exact-form resolution is additionally retained.
- **No legacy support**: Earlier fixture-store schemas are rejected; no migration or dual-version reader is provided.
- **Offline parsing**: Review verifies the selected body digest, invokes the current `AcquisitionProcessor`, and records handler outputs without source-run processing state.
- **No production enablement**: Parser review is diagnostic; route budget and publication gates remain unchanged.

## Acceptance

- Menu actions and plan switching follow the shared review console pattern.
- Filling a fixture fetches plan-selected bodies with explicit network consent and no acquisition run.
- Form 4 parser output is generated from verified fixture bytes and can be compared/analyzed offline.
- Old fixture schema is rejected rather than migrated.
