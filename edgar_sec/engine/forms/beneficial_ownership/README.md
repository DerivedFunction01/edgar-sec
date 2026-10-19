# beneficial_ownership

Layer 3 (engine) beneficial ownership parsing and XML serialization for SEC Schedule 13D and Schedule 13G.

## Purpose

Extracts structured beneficial ownership reporting matrices and narrative disclosures from normalized SEC filings. It maps cover page reporting person matrices (Slots 1 through 14 for 13D, Slots 1 through 12 for 13G) and narrative items (Items 1 through 7 for 13D, Items 1 through 10 for 13G) into conforming SEC XML schema `X0202`.

The engine consumes normalized text frames produced by `normalize_document`, avoiding brittle HTML table geometry heuristics. Cover boundaries, section sequences, and canonical checkbox tokens are resolved upstream during document normalization.

## Contracts

- **Sequential text extraction**: Reporting person disclosure matrices are extracted from the normalized cover text slice without inspecting cell coordinate geometries.
- **Unified 13D/13G matrices**: Reporting person disclosure matrices support both Schedule 13D (14 slots) and Schedule 13G (12 slots) using semantic tag mapping.
- **Upstream glyph normalization**: Checkbox tokens and symbolic font glyphs are resolved prior to matrix extraction; the parser accepts canonical bracket tokens `[X]` and `[ ]`.
- **Zero narrative regex passes**: Statutory narrative items are consumed directly from the normalization result's section sequence.
- **XML schema conformance**: Generated XML adheres to SEC schema `X0202` with namespace `http://www.sec.gov/edgar/schedule13D` or `http://www.sec.gov/edgar/schedule13G`.

## Deliberate gaps

- **Paper filings**: Paper-routed stub documents bypass structured XML rendering.
