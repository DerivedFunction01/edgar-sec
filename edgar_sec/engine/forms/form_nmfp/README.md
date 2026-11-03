# form_nmfp

SEC Form N-MFP money market fund reporting (Layer 3: Engine).

## Purpose

Provides native XML pass-through for all three schema generations, typed
parsing of the current (N-MFP3, v2.0) and prior (N-MFP2, v2.4) schedule
shape into domain models, canonical XML rendering through the shared
builder, and semantic review analysis.

## Contracts

- **Byte-Identical Native Pass-Through**: Filings of every generation pass
  through with byte identity via `passthrough_sec_xml` against
  `N_MFP_XML_SPEC`; older-version XML is never converted forward.
- **Generation From Namespace**: The schema generation is read from the
  root namespace (`nmfp`, `nmfp2`, `nmfp3`), never from the form code.
- **Canonical Namespace**: A canonical render is emitted in the current
  generation's namespace, matching the current technical specification.

## Deliberate gaps

- **Generation 1 body**: The retired part-based generation 1 schema yields
  header identity only; its schedule body rides pass-through unmodelled.
- **Liquidity and yield series**: Series- and class-level daily/weekly
  liquidity and yield detail are preserved by pass-through, not typed.
