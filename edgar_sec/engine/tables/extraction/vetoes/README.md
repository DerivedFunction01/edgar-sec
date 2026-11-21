# vetoes

## Purpose

Refusal evidence over claimed families: the term vetoes (statement and note
channels, over the shared veto core) and the PPE veto pair (evidence and
specs) that the claiming chain composes ahead of the precision pass.

## Contracts

- **A veto is a refusal over an otherwise-claimed family**, applied in
  `cascade.competition`'s composed chain — the PPE pass over the gated set
  first, the precision pass second; a veto never issues a claim of its own.
- **Veto terms are data in the veto modules' tables**, read over text
  normalized by `core.normalize`; no veto re-implements normalization.

## Deliberate gaps

- **No other refusal mechanism lives here**: genre and section refusals are
  seats (`seats/`); this folder holds only the claim-level vetoes.
