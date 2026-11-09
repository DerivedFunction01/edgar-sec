# form_s6

Domain models for Form S-6, the registration statement unit investment
trusts file under the Securities Act of 1933, its S-6/A amendments, and
Rule 487 pricing amendments: the family's processing profile and section
taxonomy over the shared text and table-geometry machinery. The section
vocabulary is the one filed specimens evidence in their tables of
contents and body headings. Rule 487 filings are amendments to Form S-6
that carry the full priced prospectus body, so one vocabulary serves
the whole line.

## Contracts

- **Text path**: the profile offers RAW and RENDER_TO_TXT with text
  preferred; S-6/A and 487 resolve to the same catalog entry through
  the family alias.
- **Section resolution**: with the profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings of the family project as
  FormS6Report.

## Deliberate gaps

- **No XBRL leg**: the profile claims no XBRL support; the family's
  text-era population is served by the text path.
- **No exhibit model**: exhibits resolve as a taxonomy section where
  a body carries an exhibit index.
- **No notes-sequence flag**: notes detection was not measured for
  this family.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entry directly.
- **S-6EL24 excluded**: the catalog-silent S-6EL24 line is a different
  legacy line and does not resolve to this family.
