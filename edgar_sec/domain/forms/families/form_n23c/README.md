# form_n23c

Domain models for the N-23C closed-end fund notice families: N-23C-1
monthly purchase statements under Rule 23c-1, N-23C-2 redemption
notices under Rule 23c-2, and the Form N-23C-3 repurchase-offer
documents under Rule 23c-3 filed as the N-23C3A, N-23C3B, and N-23C3C
strings. Each family's processing profile and section taxonomy sits
over the shared text and table-geometry machinery; the vocabularies
are the ones filed specimens evidence, established by a specimen
census of the line's filing population.

## Contracts

- **Text path**: each profile offers RAW and RENDER_TO_TXT with text
  preferred; every amendment and schedule string resolves to its
  family's catalog entry through the family aliases.
- **Section resolution**: with each profile's sections flag set,
  normalize and the shared analysis path resolve sections from the
  catalog entry's taxonomy items, in filed order.
- **Report projection**: filings project as FormN23C1Report,
  FormN23C2Report, or FormN23C3Report by family.

## Deliberate gaps

- **Unclaimed captions**: the N-23C-2 numbered statements and the
  N-23C-3 offer terms for payment and for increase in shares appear
  in specimens only as parenthesized table captions or run-in
  numbered lines, which the section detector does not claim; they
  ride as body text, and the taxonomies carry only captions the
  detector resolves on specimens.
- **No XBRL leg**: no specimen in the census carries an XBRL
  instance, so the profiles claim no XBRL support.
- **No exhibit model**: companion documents ride inside the primary
  document of these filings; no separate exhibit handling is built.
- **No bespoke review analyzer**: the shared analysis path reads the
  catalog entries directly.
- **Paper-era absence**: primaries that are .paper placeholders have
  no body to process; the text path serves their absence rather than
  manufactured content.
