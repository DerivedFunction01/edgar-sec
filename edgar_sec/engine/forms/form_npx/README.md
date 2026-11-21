# form_npx

SEC Form N-PX proxy voting record processing (Layer 3: Engine).

## Purpose

Provides native XML pass-through for the submission and the companion
proxy voting record, typed parsing of the cover page and vote table,
conversion of the pre-XML text era (SGML table blocks and the columnar
HTML table) into the current v3.1 model, canonical XML rendering through
the shared builder, and semantic review analysis.

## Contracts

- **Byte-Identical Native Pass-Through**: Submissions and vote tables
  conforming to the official N-PX / N-PX CTR XML technical specifications
  (v3.1) pass through with byte identity via `passthrough_sec_xml`
  against `N_PX_XML_SPEC`.
- **Companion Vote Records**: In the XML era the cover submission and the
  proxy vote table are separate documents of one filing; a cover-only
  document signals that votes live in the companion document.
- **Converted Dates**: Text-era meeting and period dates normalize to the
  MM/DD/YYYY schema shape through the shared date parser; unparseable
  dates are carried as filed, never invented.

## Deliberate gaps

- **Text-era layout tail**: Text layouts outside the two attested shapes
  yield a cover-only canonical document and a review signal, not rows
  guessed from free text.
- **CTR cover tail**: The CTR summary fields beyond the shared cover core
  ride pass-through unmodelled.
