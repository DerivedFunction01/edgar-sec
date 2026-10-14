# Acquisition Fixtures & Review Console Follow-up

**Status: implemented.** The acquisition fixture/review console uses the shared inventory-style menu and a parser-body fixture contract. Its current behavior is evidenced by the acquisition operator, fixture store, review builder, and mirrored tests.

## Behavior

The menu exposes create, run-level fill, deterministic list, parser review generation, compare, offline analyze, `s` to switch the active S6 plan, and exit. Fixture and run selections are discovered and paginated. Fill captures all acquired selected staged bodies in a compatible run; it does not ask for target, attempt, capture, hash, byte-limit, or consent input. Fixture fill uses the shared configured body-size ceiling and makes no network requests.

The schema-v2 fixture is pinned to the published S6 plan and stores only selected document bytes plus parser metadata. It does not retain raw HTTP responses, bundle containers, lazy-index pages, failed attempts, or S10 results. Schema v1 response-group fixtures are rejected; there is no migration or dual-version reader.

Review generation verifies fixture bytes and invokes the current acquisition-engine handlers offline. It does not require the source run's work order, processing result, or receipt. It writes a manifest and versioned per-case parser artifacts/outputs. Compare and analyze validate those artifacts without accessing fixture bodies or making network requests. Review output is diagnostic and does not publish snapshots.

## Contracts

- **Active plan**: Plan discovery returns validated published S6 plans. The selected plan is session-local; switching it never changes an existing fixture.
- **Plan-pinned fixture**: Create pins plan ID, digest, and schema version. Fill refuses a run from another plan.
- **Run-scoped fill**: Capture identity groups the current acquired selected bodies from one run. Repeated fill is idempotent for an unchanged body set.
- **Selected body only**: Fixture bytes are the exact selected staged parser input. Source response history and failed attempts remain in run evidence.
- **No legacy support**: The previous response-group schema, per-target/attempt fill path, and manual capture/target filters are removed; no on-disk fixtures require migration.
- **Offline parsing**: Review verifies the selected body digest, invokes the current `AcquisitionProcessor`, and records handler outputs without source-run processing state.
- **No production enablement**: Parser review is diagnostic; route budget and publication gates remain unchanged.

## Acceptance

- Menu actions and plan switching follow the shared review console pattern.
- Filling a run captures eligible selected bodies without raw-response retention or manual ID/hash entry.
- Form 4 parser output is generated from verified fixture bytes and can be compared/analyzed offline.
- Old fixture schema is rejected rather than migrated.
