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

## Contracts

- **A label is removed only when corroborated**: Firm markers (shape alone on line) are removed on their own; candidates require validated runs.
- **Tables and sentences are not page sequences**: Financial shapes refused before patterns; function-word lines treated as prose.
- **A table of contents is the one place page labels are content**: Exclusion is parameterized via `context["toc_lines"]`.
- **A generated token is never a source marker**: Rendered tokens carry only id; page number, namespace, coordinates, removability in sidecar.
- **Inferred boundaries are metadata only**: Not removable; emitted under `annotate` only.
- **Coordinate-safe removal**: Whole-line takes trailing newline; table overlaps widen; mid-sentence joins with space.
- **Mask/restore preserves line count and bytes**: One token per line masked with newline intact.
- **An analysis with wrong `source_text` is discarded and recomputed**: Offsets would refer to wrong frame.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

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
