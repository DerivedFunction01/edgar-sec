# S11 Pre-approval Evidence Readiness

**Status:** Evidence and contract gap inventory only. This is not S11 design approval and does not authorize durable payload publication or cleanup.

## What is verified

- S9 acquisition tests exercise direct targets, bundle-sequence extraction, retained response identity, and fixture replay using synthetic bodies and temporary stores.
- S10 tests exercise operation pins, raw preservation, route/handler dispatch, test-budgeted text normalization, retry identity, and refusal without body access when a budget is unavailable.
- Production `DEFAULT_PROCESSING_BUDGETS` is empty. Test-injected budgets and synthetic/legacy golden files are not production route/handler evidence.
- No tracked S9 acquisition-body fixture currently provides a representative provenance chain from a pinned S6 target through S9 response/selected digests and S10 operation/result fingerprints.
- The acquisition CLI's `publish`, `snapshot status`, and `review audit` surfaces remain placeholders. There is no acquisition-owned durable snapshot writer, query adapter, publication receipt, or cleanup authorization path.

## Evidence still required

| Case | Existing coverage | Missing evidence |
|---|---|---|
| Inventory-index direct target, catalog-direct target, and bundle-sequence selected child | Synthetic acquisition and processing tests exercise the mechanics | Reviewed source bodies with pinned S6 plan/target identity, S9 response and selected-body digests, and S10 operation/result fingerprints |
| Text, HTML/iXBRL, standalone XML, data, binary/PDF routes | Golden or synthetic engine tests cover parts of dispatch and fail-closed behavior | Representative S9-to-S10 cases; measured input, output, and working-set envelopes for each route/handler allowed to derive output |
| Missing, ambiguous, malformed, oversize, and processing-failure outcomes | Unit tests cover individual refusal and preservation paths | Evidence-linked cases showing the complete S6/S9/S10 result and the resulting publish eligibility decision |
| Repeated identical bytes across targets/plans/CIK provenance | Contracts describe separate payload and provenance identities | Acceptance test proving digest deduplication preserves every provenance relation |
| Same bytes processed with changed handler/options | Worker tests reject stale prior fingerprints | Snapshot-level proof that changed fingerprints produce a new representation without replacing the older one |
| Publication, interruption, CAS refusal, retention, cleanup | Generic DAG primitives exist; acquisition does not adapt them | Acquisition-specific validation, publication/recovery, query/audit, receipt, and cleanup behavior and tests |

Legacy `document_storage` fixtures and test-only injected budgets do not satisfy these evidence requirements. Unsupported PDF extraction, Form 4 XML, and unreviewed family lazy-index triggers remain disabled.

## Contract decisions before approval

1. Pin the publication base: at run projection or at publish time. The current run manifest does not pin a branch/base snapshot, while the proposal describes compare-and-swap against a base.
2. Define publish eligibility for nonterminal/failed operation results and whether an allow-errors mode exists.
3. Define a publication receipt, including recovery if the branch pointer advances but receipt creation is interrupted. The existing body-consumption receipt proves only the S10 handoff and does not authorize deletion.
4. Define which run files may be removed after verified adoption or explicit discard, and how active runs/locks are protected.
5. Define acquisition snapshot query/status and integrity-audit guarantees, including whether an audit rehashes uncompressed payloads. This is separate from the S9/S10 `review audit` placeholder.
6. Select the versioned schema contract. `representation_materialization_contract.md` is an iteration design with work-order schema v2; the current acquisition work order is v3.

## Safe path to approval

Obtain provenance-pinned representative source/processing cases first. Measure and register only evidenced route/handler/version budgets; keep other transforms raw-only. Add the missing cross-plan identity tests, then record contract amendments, residual limitations, and an explicit approver/date in the approval artifact required by S11. Only after that decision should the publisher, acquisition snapshot queries, publication receipt, and cleanup authorization be implemented.
