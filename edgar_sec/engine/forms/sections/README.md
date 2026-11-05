# sections

Structural section sequence analysis and financial statement notes detection in Layer 3 (`engine/`).

## Purpose

This package resolves statutory Part/Item sections and Financial Statement Notes across normalized filing text. Rather than evaluating individual lines in isolation, it evaluates candidate headings against document-level monotonic progression and contiguity constraints, preventing inline prose cross-references and unpaginated navigation clusters from corrupting document structure.

## Contracts

- **Spine-plus-displacement assembly (items)**: The item sequence is the longest canonical-order run of genuine candidates (the spine) plus any genuine candidate whose exclusion is a single local fault — a pairwise inversion against a spine member or a displacement across the spine — carried in document order and marked `displaced`. Duplicate detections of one ordinal are resolved first (first disjoint claimant wins) and are never displacements. A stream whose faults do not decompose into independent local ones falls back to first-fit monotonic selection, unchanged, and marks the sequence `disordered`. Notes detection keeps first-fit monotonic progression throughout.
- **Contiguity invariant for grouped headings**: Multi-item lists (`Items 1, 1A, and 1B` or `Notes 4 and 5`) must form a strictly adjacent chain in canonical order ($\Delta = 1$); lists with gaps ($\Delta > 1$) are rejected as disjoint prose references.
- **Dense pseudo-TOC isolation**: Candidate runs with line spacing $\Delta_{\text{line}} \le 3$ and zero substantive prose are classified as navigation artifacts and excluded from section assignments.
- **Omitted item monotonicity**: Sections marked with statutory omission markers (`[Omitted]`, `Not Applicable`, `None`, `[Reserved]`) advance sequence state with `is_omitted=True` without halting progression.
- **Scoped notes activation**: Financial note detection is active only within the financial statements block, insulating it from prose references in MD&A or Risk Factors.

## Deliberate gaps

- **Cross-part item renumbering**: Form 10-Q Part I and Part II both contain an `Item 1`; callers track the active Part context across parts rather than treating the whole document as a single flat ordinal space.
- **Sub-item letter exhaustion**: Notes with non-numeric suffixes (e.g. `Note 14A`) map to their base integer ordinal for sequencing.
