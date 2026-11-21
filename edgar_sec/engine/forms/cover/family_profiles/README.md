# `edgar_sec/engine/forms/cover/family_profiles` — cover family profiles by report kind

One module per report kind: annual reports, foreign-issuer forms, fund
forms, prospectus and offering communications, schedule statements,
Exchange Act notices and Section 12 registrations, Regulation A reports,
ABS reports, and a residual module for the kinds with no sibling in the
registry. Each module holds the cover-profile builders for its kind,
composed from the shared kit in `edgar_sec.engine.forms.cover.profiles`.

## Purpose

A family's cover profile is a builder over shared vocabulary: the kit
supplies the profile constructor and the common labels, and a builder
adds only its kind's boundary signals, face-sheet labels, and evidence
packs. Grouping by report kind keeps a kind's builders — and the
vocabulary choices they share — in one place.

## Contracts

- **Builders are pure composition**: a builder reads domain taxonomy and
  evidence packs and returns a `CoverProfile`; it registers nothing and
  mutates no shared state.
- **Assembly lives in `profiles`, not here**: `COVER_PROFILES` in
  `profiles` is the registry; this package only supplies the builders it
  composes, imported there at assembly time.

## Deliberate gaps

- **Flagship-kind builders stay in `profiles`**: the annual, quarterly,
  current-report, registration, and beneficial-ownership builders for
  the flagship forms (10-K, 10-Q, 8-K, S-1, 13D/13G) are kit-level
  builders there, so the annual module here holds the remaining
  annual-report families (18-K, 11-K, 40-F), not the 10-K builder.
