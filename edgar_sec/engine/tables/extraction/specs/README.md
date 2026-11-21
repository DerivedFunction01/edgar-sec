# specs

## Purpose

Per-family evidence spec data: the measured vocabulary, pattern, and bound
tables that the evidence builders (`evidence/`, `pension/`) and the form-test
aggregator read. Data only — no evaluator logic lives here.

## Contracts

- **Every spec module reads its family's profile from `core.subjects.profiles`**: the
  profile registry is the single home of the supported family set.
- **Every pattern, bound, and exclusion carries its measured value** and a
  provenance reference to the calibration record it came from (the parent
  package's registry contract).
- **A family with no spec module has no evidence specs**: absence is the
  mechanism, matching the profile registry.

## Deliberate gaps

- **Separator specs live with their evidence**: statement separators in
  `separators/`, note separators in `note_separators/`, pension specs in
  `pension/` — pairs are not split to fill this folder.
