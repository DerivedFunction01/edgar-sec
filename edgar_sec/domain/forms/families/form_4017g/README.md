# form_4017g

Domain models for Form 40-17G, the fidelity-bond filing management
investment companies make under Rule 17g-1, its 40-17G/A amendments,
and 40-17GCS claim notices: the family's processing profile and
section taxonomy over the shared text and table-geometry machinery.
The section vocabulary is the bond instrument's own blocks, which a
specimen draw of the family's filing population evidences; many
filings are a transmittal letter or a rider with no instrument blocks,
and those resolve no sections.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; 40-17G/A and 40-17GCS resolve to the same catalog entry
  through the family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form4017GReport.

## Deliberate gaps

- **No XBRL leg**: no specimen in the draw carries an XBRL instance,
  so the profile claims no XBRL support.
- **No paper or PDF handling**: .paper and PDF primaries ride their
  own paths under the format rules; the family builds no handling
  for them.
- **No rider model**: bond riders arrive as repeated short blocks
  with filer-specific numbering; no taxonomy item claims them.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
