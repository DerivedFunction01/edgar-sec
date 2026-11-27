# Section corpus

Fixture corpus for the section detector, in simplified form: skeleton
texts carrying the detector behaviours the banked full-filing corpus
existed to pin, each with its expected resolutions.

## Layout

- `simplified/` — one small text per specimen, plus `specimens.json`:
  one entry per specimen naming its family, its text, the behaviour it
  pins, its TOC span where the specimen carries one, and `expected`
  (the resolutions the corpus test asserts, migrated from the banked
  corpus's index).
- `taxonomies.json` — per slug, the section taxonomy the specimens are
  judged against, in the registry's item shape. Two slugs
  (`form_n23c2`, `form_n23c3`) carry `"corpus_restored": true` on items
  the family build had trimmed only because the detector could not
  resolve them; the corpus judges against the restored vocabulary.
  The taxonomies stay a fixture file, not the registry, so the corpus
  survives registry changes and judges the detector alone.

## Conventions

- The corpus test (`tests/engine/forms/sections/items/test_section_corpus.py`)
  drives `detect_section_sequence` directly over the skeleton texts
  and the banked taxonomy — never the family registry.
- `form_n23c3` specimens are judged with run-in section titles enabled
  (the family's processing profile opts in via
  `section_run_in_titles`); every other slug runs the detector default.
- A specimen whose honest resolution is empty stays in the set: the
  transmittal-letter control is evidence, not noise.
- The banked full texts are not tracked: `texts/` under this directory
  is git-ignored, and a re-banked filing text never re-enters the tree.
  The corpus builder (`edgar_sec.tools.section_corpus`) still banks
  full specimens on demand for detector work; its output is a local
  working product, not a fixture.
