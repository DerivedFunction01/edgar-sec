# Section corpus

Fixture corpus for the section detector: its input, banked once per
specimen, so detector tests never re-run normalization.

## Layout

- `texts/<slug>/<accession>__<document>` — the specimen's normalized
  text, exactly as normalization produced it.
- `taxonomies.json` — per slug, the section taxonomy the specimens are
  judged against, in the registry's item shape. Two slugs
  (`form_n23c2`, `form_n23c3`) carry `"corpus_restored": true` on items
  the family build had trimmed only because the detector could not
  resolve them; the corpus judges against the restored vocabulary.
- `index.json` — one entry per specimen: slug, form, accession,
  document, era, text path, the normalization TOC span, `baseline`
  (resolutions when banked) and `expected` (resolutions the corpus
  test asserts; equal to `baseline` at banking, afterwards changed
  only by a deliberate, reviewed corpus edit).
- `dropped_texts.json` — the specimens whose texts are not tracked:
  the re-proof showed each regenerable from the EDGAR archives on the
  corpus builder (byte-identical, or byte-differing with resolutions
  preserved). Each entry names the specimen, its text path, its class,
  and its banked size and SHA-256. Specimens the archives no longer
  serve stay banked in `texts/` — those texts are the surviving copy.

## Conventions

- The corpus test (`tests/engine/forms/sections/items/test_section_corpus.py`)
  drives `detect_section_sequence` directly over banked text and the
  banked taxonomy — never the family registry — so the corpus survives
  registry changes and judges the detector alone.
- `form_n23c3` specimens are judged with run-in section titles enabled
  (the family's processing profile opts in via
  `section_run_in_titles`); every other slug runs the detector default.
- Specimens whose honest resolution is empty stay in the corpus:
  transmittal-letter primaries and bodies whose headings never reach
  normalized text are evidence, not noise.

## Regenerating or extending

Bank specimens with the corpus builder (jobs name form, accession,
document, slug, and era):

```bash
python -m edgar_sec.tools.section_corpus.build --jobs jobs.json \
    [--specimen-dir DIR] [--refresh-taxonomy]
```

Without `--specimen-dir`, bodies are fetched from the EDGAR archives;
with it, a job's `file` names a local body. A slug's banked taxonomy
is written only when the slug is new or `--refresh-taxonomy` is given.

The dropped specimens' coverage lives in the tooling layer:
`regen_check.py` beside this README re-banks them from the archives
and verifies each against `dropped_texts.json` and the index's
`expected`, on demand (it needs `SEC_USER_AGENT`); the offline corpus
test covers the banked specimens and asserts the registry's
completeness against the index.
