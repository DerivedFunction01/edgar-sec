# form_rega

Engine machinery for SEC Regulation A filings: the XML kinds
(1-A offering statements, 1-K annual reports, 1-Z exit reports)
and the text kinds (1-SA semiannual reports, 1-U current reports,
1-A-W withdrawal letters). Layer 3 (engine), consuming the
`form_rega` domain models and the shared `edgarSubmission` header
machinery in `engine/forms/common`.

## Purpose

Reads the header of every Reg A XML kind through the shared
header parser, dispatches the kind from `headerData/submissionType`,
and extracts the issuer block and kind-specific presence signals
for review. The text kinds ride the shared cover/section analysis
with family cover profiles and item taxonomies; withdrawal letters
are read as letters, with the file number, registrant, and
withdrawal statement as their face fields.

## Contracts

- **Native XML passes through**: a primary matching its kind's
  schema spec is returned byte-identical.
- **No lossy rebuild**: a payload that does not match the spec is
  refused, never rebuilt from the partial review model.
- **Kinds come from the header only**: on the XML leg the form
  code on the filing index never overrides
  `headerData/submissionType`; a disagreement is a review anomaly.

## Deliberate gaps

- **Offering and financial detail stay in the payload**: review
  records their presence and headline amounts; full element
  modeling of the offering and financial blocks is not attempted.
- **Paper-era primaries stay raw**: the 1-A paper rows predate
  electronic filing and carry no document to model.
