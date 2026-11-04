# form_sd

Engine machinery for Form SD, the specialized disclosure report:
the Rule 13p-1 conflict-minerals election and the Rule 13q-1
resource-extraction payments election on one thin face. Layer 3
(engine), consuming the `form_sd` domain package and the shared
cover machinery.

## Purpose

Reviews the SD face: registrant and commission file number off the
cover, the rule-election checkbox pair resolved through the shared
checkmark machinery, the Section 1 / 2 / 3 items, and the EX-1.01 /
EX-2.01 companion signals the primary itself records.

## Contracts

- **Kind is read off the filing's own face**: the resolved rule
  checkbox pair classifies the filing (conflict minerals, resource
  extraction, combined); item presence is only a fallback when no
  box resolves, and a filing with neither is reported undetermined,
  never guessed.
- **Companions are signals, never parsed**: EX-1.01 (conflict
  minerals report) and EX-2.01 (payment report) are recorded as
  type-and-presence signals from the primary's own exhibit
  references. EX-2.01 content is Inline XBRL and routes to XBRL
  provenance, not text parsing.

## Deliberate gaps

- **No exhibit bodies**: companion documents are not fixtures and
  are never opened by this analyzer; only the primary's references
  to them are read.
