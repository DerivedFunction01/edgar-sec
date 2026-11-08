# form_18k

Domain models for Form 18-K, the annual report foreign governments and
their agencies file, and its 18-K/A amendments: the family's processing
profile and section taxonomy over the shared text and table-geometry
machinery. The section vocabulary is the one filed specimens evidence,
established by a specimen census of the family's filing population
after the family's earlier raw-only disposition proved to rest on
documents of another form.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; 18-K/A resolves to the same catalog entry through the
  family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  Form18KReport.

## Deliberate gaps

- **No XBRL leg**: no specimen in the census carries an XBRL instance
  or an inline flag, so the profile claims no XBRL support.
- **No exhibit model**: no specimen index carries an EX-* document.
- **No notes-sequence flag**: notes detection was not measured for
  this family; the notes block resolves as a taxonomy section.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
- **Paper-era absence**: primaries that are .paper placeholders have
  no body to process; the text path serves their absence rather than
  manufactured content.
- **No table classification**: statement-vs-schedule classification
  of lifted tables is unbuilt; presence was measured, classifiability
  was not.
