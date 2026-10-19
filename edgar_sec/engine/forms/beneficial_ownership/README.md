# beneficial_ownership

Layer 3 (engine) beneficial ownership parsing and XML serialization for SEC Schedule 13D and Schedule 13G.

## Purpose

Extracts supported beneficial ownership reporting matrices and narrative disclosures from normalized SEC filings. It maps cover-page values and recognized narrative fields into the SEC `X0202` XML vocabulary; analysis reports schema requirements that remain missing or invalid.

The engine consumes normalized text frames produced by `normalize_document`, avoiding brittle HTML table geometry heuristics. Cover boundaries, section sequences, and canonical checkbox tokens are resolved upstream during document normalization.

## Contracts

- **Sequential text extraction**: Reporting person disclosure matrices are extracted from the normalized cover text slice without inspecting cell coordinate geometries.
- **Unified 13D/13G matrices**: Reporting person disclosure matrices support both Schedule 13D (14 slots) and Schedule 13G (12 slots) using semantic tag mapping.
- **Upstream glyph normalization**: Checkbox tokens and symbolic font glyphs are resolved prior to matrix extraction; the parser accepts canonical bracket tokens `[X]` and `[ ]`.
- **Zero narrative regex passes**: Statutory narrative items are consumed directly from the normalization result's section sequence.
- **Schema fields only**: Extractor provenance and unparsed narrative text are persisted in `operations/unparsed_sections.json`, outside the SEC XML payload.

## Deliberate gaps

- **Paper filings**: Paper-routed stub documents bypass structured XML rendering.
