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
| `models.py` | The label patterns, the 20 `PageMarkerKind` shapes, `PageArtifactPolicy`, `PageMarkerTerminalState`, the immutable analysis/marker/decision/artifact records, `PROSE_GUARD_STOP_WORDS`, `PAGE_HINT_ROLES`. |
| `candidates.py` | Contextual scan: `firm_markers`, `classify_candidate`, `all_candidates`, `promote_groups`, plus the geometry (`candidate_template`, `has_numeric_data_shape`, `cluster_is_table_like`) and prose guard. |
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
  removal overlapping a compact rendered `<TABLE>` (≤ 12 lines) widens to the
  whole table; a removal landing mid-sentence between a non-terminal word and a
  lowercase continuation is joined with a space rather than concatenated.
- **Mask/restore preserves the line count and the bytes.** `signatures` masks one
  token per line with that line's newline intact.
- **An analysis whose `source_text` is not the document is discarded and
  recomputed** — its offsets would refer to a different frame.

## Public surface

| Import from | Names |
| :--- | :--- |
| `page_markers.models` | `PageMarkerAction`, `PageMarkerDecision`, `PageMarkerAnalysis`, `PageMarker`, `PageMarkerKind`, `PageMarkerSpan`, `PageCandidate`, `PageNumberRun`, `InferredBoundary`, `TemplateEvidence`, `PageBreakArtifact`, `PageArtifactPolicy`, `PageMarkerTerminalState`, `PAGE_MARKER_PATTERNS`, `RE_PAGE_VALUE`, `PROSE_GUARD_STOP_WORDS`, `PAGE_HINT_ROLES` |
| `page_markers.detector` | `analyze_page_markers`, `find_page_markers`, `is_page_marker_line` |
| `page_markers.candidates` | `firm_markers`, `classify_candidate`, `all_candidates`, `promote_groups`, `candidate_template`, `has_numeric_data_shape`, `cluster_is_table_like`, `looks_like_prose`, `prose_stop_words`, `toc_lines`, `line_offsets`, `marker_for_candidate` |
| `page_markers.sequence` | `validate_group`, `heal_run`, `unify_alternating_runs`, `monotone_fraction` |
| `page_markers.units` | `LogicalUnit`, `classify_units` |
| `page_markers.templates` | `analyze_repeating_headers`, `Observation`, `clean_template`, `eligible_line`, `collect_window`, `clusters`, `merge_observations` |
| `page_markers.artifacts` | `render_page_artifact`, `token_kind_for`, `note_template`, `normalize_template_text`, `template_id_for`, `build_page_artifact_metadata` |
| `page_markers.policy` | `apply_page_markers`, `apply_text_policy`, `apply_html_policy`, `apply_fast_html_page_policy` |
| `page_markers.signatures` | `find_signature_regions`, `mask_signature_regions`, `restore_signature_regions`, `normalize_signature_marker`, `heal_mangled_signature_text`, `signature_block_has_mangled_text`, `is_signature_label_line`, `is_conformed_signature_line`, `SignatureRegion`, `RE_CONFORMED_SIGNATURE`, `RE_POA_SIGNER` |

## Command surface

None. Called from the normalization pipeline.

## Mirrored tests

| Module | Test |
| :--- | :--- |
| `models.py` | `tests/engine/document/page_markers/test_models.py` |
| `candidates.py` | `tests/engine/document/page_markers/test_candidates.py` |
| `detector.py` | `tests/engine/document/page_markers/test_detector.py` |
| `sequence.py` | `tests/engine/document/page_markers/test_sequence.py` |
| `units.py` | `tests/engine/document/page_markers/test_units.py` |
| `templates.py` | `tests/engine/document/page_markers/test_templates.py` |
| `artifacts.py` | `tests/engine/document/page_markers/test_artifacts.py` |
| `policy.py` | `tests/engine/document/page_markers/test_policy.py` |
| `signatures.py` | `tests/engine/document/page_markers/test_signatures.py` |

One test per module; all nine exist.

## Deliberate gaps

- **This package does not find the table of contents.** V1 called the cover TOC
  finder from inside the candidate scan, which is the reverse of this package's
  dependency direction. A caller that has located a contents span passes it in
  through `context["toc_lines"]` or `toc_lines(text, span_finder)`. With no span,
  nothing is excluded, so a document analysed without that parameter treats
  contents rows as candidates. Deliberate: it is the one-way dependency the
  layering requires.
- **`RE_PAGE_SUFFIX` is not redefined here.** It already exists in
  `edgar_sec.engine.tables.toc.patterns` and the two meanings are one pattern.
- **`PAGE_HINT_ROLES` is published but not resolved here.** The `break` subset is
  what substitutes a page-split sentinel during projection, and already lives
  narrowed in `edgar_sec.engine.document.html.breaks.PAGE_BREAK_HINT_TOKENS`. The
  attribute-value resolver that turned a node's `class`/`id`/`style` into roles
  has no caller: page furniture is now driven by validated runs, not attribute
  naming, so the vocabulary is kept as documentation of the alias space.
- **A discovered-but-unclaimed candidate is reported, not removed.** It appears in
  `PageMarkerAnalysis.unresolved` as `line:text` and moves the terminal state to
  `UNRESOLVED`, so a document that yielded no removals is diagnosable. Not an
  error, and it does not fail the pipeline.
- **The sidecar has no consumer.** `build_page_artifact_metadata` is landed and
  tested; `apply_page_markers` returns its artifacts, but no caller records them
  (see `edgar_sec/engine/document/README.md`).
- **`signatures` does not own signature *rendering*.** It locates regions, masks
  and restores them, and heals mangled names; choosing the columns is the reflow
  package's concern. `signature_block_has_mangled_text` is the confirmation
  predicate `heal_mangled_signature_text` documents its precondition in terms of;
  it has no caller yet.
- **`LogicalUnit` is page-marker local, deliberately.** It is coarser than a
  general document-structure model on purpose: its only job is to tell a table
  from a paragraph well enough that a repeating table is not mistaken for a
  repeating page. Promoting it to `foundation` would make a page-marker
  heuristic look like a document primitive.
- **Metadata-only boundary reports are not carried.** V1 carried a per-region
  classification of source intervals no validated family claimed
  (`referential_labels` / `weak_numeric` / `likely_pageless`); it had no caller
  and no producer of removal authority, so it is not reproduced. V1's
  `line_shape` feature helper and raw hint-attribute parsing are likewise absent.