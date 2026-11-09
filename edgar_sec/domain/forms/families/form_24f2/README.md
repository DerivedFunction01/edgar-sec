# form_24f2

Domain models for the Rule 24f-2 fee-notice line — Form 24F-2NT and
its amendments, plus the legacy 24F-2TM, 24F-2EL, and 24F-1 notices:
the family's processing profile and section taxonomy over the shared
text machinery. The section vocabulary is the numbered-caption
vocabulary filed specimens evidence, established by a specimen census
of the line's filing population across its text, HTML, and XML shapes.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; every code in the line resolves to the same catalog
  entry through the family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form24F2Report.

## Deliberate gaps

- **No XBRL leg**: the modern XML specimens are EDGAR structured
  submissions in the form's own schema, not XBRL instances, so the
  profile claims no XBRL support; their field values render as text
  and resolve no sections.
- **No fee-table model**: the registration-fee calculation resolves
  as a taxonomy section; its line items are not separately modelled.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
- **Legacy-letter absence**: the pre-template legacy notices are
  free-form letters with no caption structure; they resolve no
  sections rather than manufactured ones.
- **Colon-terminated captions**: the fee-calculation caption line
  ends in a colon in every specimen that carries it, a shape the
  shared section-candidate charset does not admit, so that section
  resolves only where a colon-free caption shape occurs; the
  vocabulary entry stands for the shapes that do occur.
