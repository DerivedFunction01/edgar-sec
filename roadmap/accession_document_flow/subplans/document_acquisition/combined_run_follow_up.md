# Combined acquisition run follow-up

## Objective

Make acquisition and processing one resumable run action. A single `acquisition run --run-id <id>` and one interactive menu action must fetch each eligible target and process its selected body as part of the same per-target execution, like `document_inventory` fetches and parses within its run. Remove the standalone `process` CLI subcommand and operator item; do not add a compatibility alias.

This changes the lifecycle boundary, not the processing safety policy. Preserve raw-first behavior, versioned operation pins, fail-closed resource admission, receipt rules, staged outputs, and the S11 publication/cleanup gate.

## Current structure and reason for follow-up

- `runner.execute_acquisition_run()` validates and locks a run, acquires eligible targets, persists target outcomes, then returns. It does not dispatch processing.
- `processing.run.execute_processing_run()` independently validates and locks the same run, selects targets already marked `acquired`, dispatches operations, and persists processing manifests and operation attempts.
- `operator.py` exposes those calls as menu items 3 and 4. `cli.py` exposes `run` and `process` as separate subcommands.
- `document_inventory` instead keeps fetch and parse in its per-accession worker, called by one run coordinator.

The separate processing coordinator was a deferral boundary in earlier subplans. The target lifecycle is to run acquisition and processing together; `process_target()` and the processing engine remain internal per-target implementation pieces, not separate entry points.

## Target execution contract

1. Projecting a plan, inspecting status, review/fixture actions, and S11 publication remain separate actions.
2. One `run` coordinator owns the run lock and processes targets serially. For each eligible target, it acquires/selects the body, commits acquisition provenance and the acquired checkpoint, then dispatches that target's requested operations before moving on.
3. The `acquired` target status remains a durable recovery checkpoint, not a user-visible phase. If interrupted after acquisition but before or during processing, a later `run` resumes processing that staged body without fetching it again. Existing completed operation results are validated and reused under current retry rules.
4. Acquisition failure prevents body processing. Processing failure does not rewrite a successful acquisition as failed; target outcomes and per-operation outcomes remain separately recorded and reported.
5. `--retry-failures` on the combined command applies to each existing retryable acquisition or processing failure according to that subsystem's retry rules. It must not refetch an already acquired target merely to retry an operation. Keep terminal refusals and blocked, unbudgeted transforms non-retryable.
6. The interactive run action retains default-no live-network authorization before any possible SEC request. A resume with only already-acquired bodies to process is offline and must not require a network confirmation. Direct CLI `run` remains an explicit caller-authorized network action.
7. Preserve the current transport byte limits, cancellation, per-target persistence, receipt validation, and no-cleanup-before-S11 rules. A single action does not publish a snapshot, discard staged files, or enable production normalization budgets.
8. Report both acquisition and operation outcomes from the combined run and read-only status surfaces. Do not expose a processing-only workers option unless a real, resource-budgeted scheduling contract is implemented; current execution is serial.

## Implementation sequence

1. Refactor run orchestration around one per-target lifecycle. Reuse the existing target acquisition, request construction, operation retry/result validation, atomic result-manifest, and operation-state helpers. Take the run lock once; avoid calling a second coordinator that tries to acquire it again. Keep the acquisition checkpoint durable so interruption never forces a repeat HTTP request for an already acquired target.
2. Integrate operation results into the `run` result and terminal-state reporting. Exercise acquisition followed immediately by processing with injected transports and test budgets; test acquired-but-unprocessed recovery with no transport calls.
3. Remove the `process` parser/import/command module and separate operator action. Fold processing-retry selection into the single run action while retaining a distinct default-no live-SEC confirmation. Reject the removed `process` command rather than preserving a shim.
4. Update offline acceptance and focused tests for the unified run, retry semantics, interruption/resume, summary output, and no-network processing of acquired bodies. Keep lower-level `process_target()` and engine tests; move command/coordinator integration coverage to the run surface.
5. Reconcile active roadmap contracts and diagrams listed below so they no longer specify fetch and process as separate user steps. Keep historic design records labeled as historic rather than silently rewriting their evidence.

## Affected code and tests

### Runtime code

- `edgar_sec/pipelines/document_acquisition/operator.py`: replace two menu actions with one run action and consolidate prompts.
- `edgar_sec/pipelines/document_acquisition/cli.py`: remove `process`; make `run` the only lifecycle execution command.
- `edgar_sec/pipelines/document_acquisition/commands/run.py`: dispatch the combined coordinator and report.
- `edgar_sec/pipelines/document_acquisition/commands/process.py`: retire after its operation is integrated into `run`.
- `edgar_sec/pipelines/document_acquisition/runner.py` and `target_runner.py`: compose acquisition and processing per target while retaining acquisition attempt evidence and checkpoints.
- `edgar_sec/pipelines/document_acquisition/processing/run.py`: retire `execute_processing_run()` as an independent lifecycle coordinator; preserve/refactor its per-target result validation, retry, manifest, and run-state helpers for use by the combined coordinator.
- `edgar_sec/pipelines/document_acquisition/commands/status.py`, `models.py`, `processing/worker.py`, `run_state/operations.py`, and `run_state/store.py`: expose operation counts/status alongside acquisition state without changing read-only inspection or append-only attempt semantics.

### Mirrored tests

- Update `tests/pipelines/document_acquisition/test_operator.py`, `test_cli.py`, `commands/test_run.py`, and `test_runner.py` for a single entry, confirmation behavior, combined summaries, and no `process` parser.
- Replace `tests/pipelines/document_acquisition/commands/test_process.py` with run-command coverage; migrate/rename `test_process_cli_integration.py` to test the integrated run path.
- Refactor `tests/pipelines/document_acquisition/processing/test_run.py` around internal processing helpers or move coordinator-level assertions to run tests. Retain `processing/test_worker.py` coverage of engine dispatch, resource refusal, receipts, and raw preservation.
- Extend `commands/test_status.py` and `run_state/test_operations.py` to cover read-only combined target/operation status.
- Extend `test_offline_acceptance.py` to run acquisition and processing through one coordinator using fake transport and test-only budgets. Add an interruption case after acquisition commit proving resume performs no HTTP refetch.
- Keep fixture/review tests that directly test per-target processing; they are not lifecycle entry points.

## Active documentation to reconcile

- `roadmap/accession_document_flow/design.md`: show one acquisition execution step containing per-target fetch then process, while retaining the network/local boundary and the later S11 gate.
- `roadmap/accession_document_flow/implementation.md`, `subplans/S9_acquisition.md`, and `subplans/S10_processing.md`: replace stale claims that the process command/coordinator is absent and describe one run lifecycle with a processing sub-contract.
- `subplans/document_acquisition/plan.md`: remove the remaining standalone S9-to-S10 integration prerequisite from the active run sequence; retain production enablement and S11 gates.
- `subplans/document_acquisition/operator.md` and `cli_inventory.md`: remove menu item 4 and the `acquisition process` entry; document one run action and its combined retry/network-confirmation behavior.
- `subplans/document_acquisition/lifecycle.md`, `run/index.md`, and `run/state.md`: replace the two-command handoff with per-target acquisition/processing and internal acquired-state recovery. Keep receipts as evidence of body consumption, not deletion permission.
- `subplans/document_acquisition/representation_materialization_contract.md`: align ownership language with local per-target acquisition plus operation materialization; keep the not-yet-implemented distribution wire contract explicitly deferred.
- `subplans/S12_operator_integration.md`: combine acquisition and processing into one offline acceptance step while preserving zero-network proof and the S11 gate.
- `subplans/document_acquisition/distribution/index.md`, `import.md`, and related worker contracts: these are planned, not implemented, but currently describe acquisition-only worker results. Reconcile them to the combined unit before implementing an acquisition distribution adapter; do not expand scope to implement distribution here.

Do not edit the frozen `subplans/document_inventory/follow_up_run_plan.md`. Keep S11 publication, durable payload layout, explicit discard/cleanup, fixture project-source mode, production normalization budgets/handlers, and the unimplemented acquisition distribution adapter outside this follow-up's implementation scope.

## Acceptance

- One menu item and one CLI subcommand perform the combined run; `acquisition process` is rejected.
- For each successful target, fake SEC acquisition is followed by requested local processing before the run advances; acquisition and operation outcomes remain independently attributable.
- Resume processes an acquired body after interruption without constructing/using SEC transport or refetching it.
- `--retry-failures` retries only independently retryable acquisition/operation work and does not refetch acquired bodies for processing retries.
- No HTTP occurs on declined live confirmation or an acquired-only offline resume. Processing failures preserve raw identity and existing no-receipt-on-pre-body-refusal behavior.
- Existing cancellation, bounded transfer, manifest integrity, operation-state, and receipt tests remain valid. No S11 snapshot parts, pointers, or cleanup actions are produced.
- Run the unified quality gate for changed code and the explicit mirrored acquisition tests; do not run `check.py --all` unless requested.
