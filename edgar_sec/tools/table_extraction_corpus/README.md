# table_extraction_corpus

## Purpose

Tooling for the table-extraction successor plan
(`.plans/2026-11-08-table-extraction-successor.md`): rebuild the retained
taxonomy corpus as context-carrying fixtures (grid, caption stack,
preceding cues, prose windows on both sides, structured location, page-break
evidence with namespace, scale), and reconcile the rebuild against the
retained corpus. The defect register defined here is shared by the plan's
later drives (derivation self-check, verdict, validation).

## Contracts

- Every compute leg (fetch, normalize, extraction) runs on Colab High-RAM
  and says so in its record; local use is authoring only.
- Retrieval is catalog-free (the facade's fetch-by-accession requires a
  published filing catalog no live session carries — the taxonomy lane's
  recorded substitution): each filing's aggregate is built from its
  Archives index, and the primary document is the one typed as the
  filing's form (lowest sequence on ties) by the filing's SGML index
  headers, or by the filing index page parsed with the repo's own
  index-page parser when the headers are not served — the directory
  listing itself carries no document types — with a largest-document
  fallback; the choice and its source are recorded per fixture and
  proven by the reconciliation's geometry-count contract.
- Labels and split are inherited from the retained corpus verbatim; this
  tooling never relabels and never modifies the retained corpus.
- New populations are labelled by `label.py`, the taxonomy lane's XBRL
  alignment method ported verbatim (role-title map, significant-digit
  scoring, schedule signatures, aligned-negative rule); it labels only
  population fixtures it is handed, never retained ones.
- A geometry that cannot be located in the annotated text frame, and a
  break whose namespace cannot be verified, are defect-register entries
  with explanations — never silent drops or guessed values.
- Reconciliation blocks on count, alignment, or label divergence and on
  any grid divergence whose canonical content stream changed.

## Deliberate gaps

- No live-SEC code of its own: acquisition rides the facade pipeline.
- Break namespaces are rebuilt from the page-marker analysis the
  normalization result carries; the rendered artifact records themselves
  are not part of that result, so a count mismatch records the namespace
  as unknown for the filing instead of widening the normalization seam.
