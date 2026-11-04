# form_abs_ee

Engine machinery for the ABS-EE companion scope: the EX-102 and
EX-103 asset-data exhibits carried by ABS-EE and 10-D submissions.
Layer 3 (engine), consuming the `form_abs_ee` domain models. ABS-EE
is exhibits-only — there is deliberately no form family here.

## Purpose

Classifies an asset-data document (EX-102 namespaced per asset
class, EX-103 namespace-less with narrative in comments), summarizes
it by streaming, and records companion presence on host submissions.

## Contracts

- **Streaming only**: asset-data files reach tens of megabytes; the
  summarizer walks the document with `iterparse`, counts records
  and comments, and clears elements as it goes — the tree is never
  materialized and no record payload is retained.
- **Comment text is content**: EX-103 narrative lives in XML
  comments (and CDATA sections); both are counted, never dropped
  silently.
- **Native XML passes through**: asset-data documents are returned
  byte-identical; anything else is refused, never rebuilt.

## Deliberate gaps

- **Per-asset fields are not modeled**: the summary stops at kind,
  asset class, record count, and narrative volume; loan-level field
  extraction belongs to a future ABS data product, not this scope.
