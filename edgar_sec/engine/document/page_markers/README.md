# `edgar_sec/engine/document/page_markers` — page structure detection and policy

## Purpose

A normalized document still says which page it is on. Those claims are printed
page furniture — an SGML `<PAGE>` tag, a wrapped label, a `page N of M` line, a
banner that recurs at the same distance from every page. This package decides
which claims are corroborated well enough to act on, then applies a declared
policy. It is the only place in the engine that deletes a line on the grounds
that the line was a page label.

Three questions, in order:

1. **What does the document claim about its own pagination?** (`detector`)
2. **Which claims are corroborated well enough to act on?** (`sequence`,
   `templates`)
3. **What happens to the validated spans, and what is recorded about them?**
   (`policy`, `artifacts`)

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | The label patterns, the `PageMarkerKind` shapes, the policy and terminal-state vocabulary, and the immutable analysis/marker/decision/artifact records. |
| `candidates.py` | The contextual candidate scan, the geometry and prose guards that keep a table from reading as a page sequence, and the caller's contents-span exclusion. |
| `detector.py` | `analyze_page_markers` — the ordered scan composing the modules below. |
| `sequence.py` | Run validation and conservative healing. |
| `units.py` | `LogicalUnit` / `classify_units` — blank-line block classification. |
| `templates.py` | `analyze_repeating_headers` and its window, clustering, and merge mechanics. |
| `artifacts.py` | The `[[SEC:KIND id=N]]` token, template normalization and ids, the deterministic sidecar. |
| `policy.py` | `apply_page_markers` and its text-frame / projected-HTML entry points. |
| `signatures.py` | Signature-region location, line-count-preserving mask/restore, letter-spaced name healing. |

## Contracts

- **A label is removed only when corroborated.** A *firm* marker — a shape that
  stands alone on its line and cannot mean anything else — is removed on its own.
  Every other label is a *candidate* and is removed only once it joins a validated
  run: same shape, same namespace, consistent distance and alignment,
  monotonically increasing.
- **Tables and sentences are not page sequences.** A line with a financial shape
  is refused before any pattern is tried; a long line carrying function words is
  prose; a cluster spaced as a dense burst is tabular. A line inside a rendered
  table is refused unless the caller has said table furniture is admissible
  (`context["allow_table_furniture"]`), and that is true only for the HTML entry
  point.
- **A table of contents is the one place page labels are content.** Its lines are
  excluded, and the exclusion is a parameter: `candidates.toc_lines` takes the
  resolver, `analyze_page_markers` reads `context["toc_lines"]`. This package
  does not import the cover TOC finder; the dependency runs one way.
- **A generated token is never a source marker.** A rendered token carries an id
  and nothing else; page number, namespace, coordinates, and removability live in
  the sidecar. Removal is decided on the source span before rendering.
- **Inferred boundaries are metadata only.** A page number inferred across a
  numeric gap is recorded with the reason that authorized it, emitted under
  `annotate` only, and is never removable.
- **Coordinate-safe removal.** A whole-line removal takes its trailing newline; a
  removal overlapping a compact rendered `<TABLE>` widens to the whole table; a
  removal landing mid-sentence between a non-terminal word and a lowercase
  continuation is joined with a space rather than concatenated.
- **Mask/restore preserves the line count and the bytes.** `signatures` masks one
  token per line with that line's newline intact.
- **An analysis whose `source_text` is not the document is discarded and
  recomputed** — its offsets would refer to a different frame.

## Public surface

Entry points, by owning module:

- `analyze_page_markers`, `find_page_markers`, `is_page_marker_line` — `detector.py`.
- `apply_page_markers`, `apply_text_policy`, `apply_html_policy`,
  `apply_fast_html_page_policy` — `policy.py`.
- `render_page_artifact`, `build_page_artifact_metadata` — `artifacts.py`.
- `analyze_repeating_headers` — `templates.py`.
- `find_signature_regions`, `mask_signature_regions`, `restore_signature_regions`,
  `heal_mangled_signature_text` — `signatures.py`.

The candidate scan (`candidates.py`), run validation (`sequence.py`), unit
classification (`units.py`), and the shape vocabulary (`models.py`) are reached
through those entry points; each module's own docstring lists its exports.

## Command surface

None. Called from the normalization pipeline.

## Mirrored tests

`tests/engine/document/page_markers/` — one test module per source module, all
collected by the committed suite.

## Deliberate gaps

- **This package does not find the table of contents.** Its candidate scan cannot
  call into the cover TOC finder without reversing the dependency direction, so a
  caller that has located a contents span supplies it through
  `context["toc_lines"]` or `toc_lines(text, span_finder)`. Without that
  parameter, contents rows are treated as candidates.
- **`signatures` does not own signature *rendering*.** It locates, masks,
  restores, and heals; choosing the columns is the reflow package's concern.
- **Regions examined and passed over are not reported.** No validated family
  classifies a source interval that no claim covered — a referential label, a
  weak numeric run, a likely-pageless stretch — so a caller cannot ask which
  regions were examined and skipped.