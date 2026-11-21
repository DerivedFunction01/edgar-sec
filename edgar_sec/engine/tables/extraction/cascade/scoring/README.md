# scoring

## Purpose

The per-table scoring half of the cascade: `classify` runs the tiered
classification cascade over one structured table; `family_scoring` scores
per-family evidence; `rule_matching` matches policy anchors and label rules
over a table's context; `ladder_attribution` lets the priced debt/lease
edge terms decide a contested pair, and contest or flip a lone ladder
claim; `score_trail` applies the score-trail edits for the signature
competition — seating a family at the claim floor and appending zero-point
notes.

## Contracts

- **Scoring names families; it does not claim**: claims issue from the
  parent package's composed claiming chain over these scores.
- **Ladder terms decide only contested pairs**: an uncontested claim is
  contested or flipped only by the priced edge terms, never by score mass.

## Deliberate gaps

- **Geometry construction is not decided here**: scoring reads built
  geometries and their channel text (the `geometry` subpackage); it builds
  neither.
