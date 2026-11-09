# form_4017f2

Domain models for Form 40-17F2, the certificate of accounting of
securities in the custody of management investment companies filed
under Rule 17f-2, and its 40-17F2/A amendments: the family's
processing profile and section taxonomy over the shared text
machinery. The taxonomy covers the blocks a specimen draw of the
family's filing population evidences after the Form N-17f-2
certificate face: the form's instructions, the management
statement, and the independent accountant's report. Many filings
carry only the accountant's report as their primary document; the
remaining blocks resolve as honest absence there.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; 40-17F2/A resolves to the same catalog entry through
  the family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form4017F2Report.

## Deliberate gaps

- **No XBRL leg**: no specimen in the draw carries an XBRL instance,
  so the profile claims no XBRL support.
- **No certificate-face model**: the numbered certificate items and
  the state identification grid are cover vocabulary, not sections.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
