# section_corpus

Layer 6. Banking for the section detector's normalized-text fixture corpus.

## Purpose

The corpus under `tests/fixtures/engine/forms/sections/section_corpus/`
holds the detector's input — normalized text banked once per specimen,
the taxonomy it is judged against, and its resolutions — so detector
tests never re-run normalization. This package is how specimens enter
the corpus: a jobs file names filings by form, accession, and document,
and each body is fetched (or read from a local specimen directory),
normalized once through the production pipeline, and banked.

## Contracts

- **Banked taxonomy is stable**: A slug's taxonomy is written from the
  family registry only when the slug is new or `--refresh-taxonomy` is
  passed; later registry edits never silently re-judge banked specimens.
- **Baseline equals expected at banking**: A fresh specimen's expected
  resolutions are its detector resolutions at banking time; afterwards
  `expected` changes only by a deliberate, reviewed corpus edit.
- **Accessions are recorded per fixture**: Every index entry carries its
  accession and document, so any specimen can be re-drawn and re-banked.

## Deliberate gaps

- **No specimen selection**: Which filings belong in the corpus is a
  census decision made elsewhere; this tool banks the specimens it is
  named.
