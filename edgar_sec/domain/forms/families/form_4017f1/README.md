# form_4017f1

Domain models for Form 40-17F1, the certificate of accounting of
securities in the custody of exchange members that management
investment companies file under Rule 17f-1, and its 40-17F1/A
amendments: the family's processing profile and section taxonomy
over the shared text machinery. The taxonomy covers the blocks a
specimen draw of the family's filing population evidences after the
Form N-17f-1 certificate face: the form's instructions, the
management statement, and the independent accountant's report.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; 40-17F1/A resolves to the same catalog entry through
  the family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form4017F1Report.

## Deliberate gaps

- **No XBRL leg**: no specimen in the draw carries an XBRL instance,
  so the profile claims no XBRL support.
- **No certificate-face model**: the numbered certificate items and
  the state identification grid are cover vocabulary, not sections.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
- **Paper-era absence**: primaries that are .paper placeholders have
  no body to process; the text path serves their absence rather than
  manufactured content.
