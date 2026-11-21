# core

## Purpose

The shared foundation of the extraction package: the context model (`context`),
typed-row structuring (`typed_rows`), the measured registry (`registry`) and the
family profile registry (`profiles`), and the text, period, and placement
primitives every other extraction subpackage builds on.

## Contracts

- **Periods bind from the whole header stack** (`typed_rows`): spanning group rows
  and per-column date or year rows compose into one label per value column; a
  value column no header cell covers binds an explicit unknown period.
- **Scale is data or explicit unknown**: a table's scale is a parsed `Scale` or
  `None`; no consumer re-derives it from rendered text.
- **Family profiles live once, as data, in the profile registry** (`profiles`):
  a family outside the registry does not compete — absence is the whole
  mechanism, never a code branch.
- **The subject-evidence map is data, not code**: `subject_evidence` loads the
  versioned flat map beside it (`subject_evidence_map.json`, next to the
  registry); it carries free-text evidence only.
- **Region is hard context** (`regions`): a geometry inside a signature region
  is never a statement candidate, whatever its vocabulary scores.

## Deliberate gaps

- **Location priors are not yet supplied**: the annual form family's location
  expectations land with their own module; until then the surface runs on
  vocabulary and shape evidence alone (the parent package's gap, held here).
