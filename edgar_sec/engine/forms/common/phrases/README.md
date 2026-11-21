# `edgar_sec/engine/forms/common/phrases` — phrase-level text signals

Source-aware phrase annotation and statutory notice filtering.

## Purpose

Owns phrase-level classification over form text: source-aware phrase matches
with offsets and neighboring lines (`phrases`), and the compiled regexes for
legal notice filtering and header artifact detection (`statutory`).

## Contracts

- **Source-aware matches**: Phrase classification returns source offsets and
  neighboring lines; matching never mutates parser input.

## Deliberate gaps

- **No boilerplate verdicts**: Whether a statutory passage disqualifies a
  value is the consuming parser's call; this package only detects and
  annotates.
