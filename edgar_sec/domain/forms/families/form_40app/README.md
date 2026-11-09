# form_40app

Domain models for Form 40-APP, the application for an exemptive order
under the Investment Company Act of 1940, and its 40-APP/A amendments:
the family's processing profile and section taxonomy over the shared
text and table-geometry machinery. The section vocabulary is the one
filed specimens evidence, established by a specimen draw over the
family's filing population, stratified by era quarter and form code.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; 40-APP/A resolves to the same catalog entry through the
  family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form40AppReport.

## Deliberate gaps

- **No XBRL leg**: no specimen in the draw carries an XBRL instance
  or an inline flag, so the profile claims no XBRL support.
- **No exhibit model**: exhibits ride the shared attachment path; the
  taxonomy names only the exhibit index section where a body carries
  one.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
- **Paper-era absence**: primaries that are .paper placeholders have
  no body to process; the text path serves their absence rather than
  manufactured content.
