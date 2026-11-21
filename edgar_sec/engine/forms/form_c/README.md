# form_c

Engine machinery for SEC Form C, the Regulation Crowdfunding
submission family (offerings, progress updates, annual reports,
terminations, withdrawals). Layer 3 (engine), consuming the
`form_c` domain models and the shared `edgarSubmission` header
machinery in `engine/forms/common`.

## Purpose

Reads the header of every Form C kind through the shared header
parser, dispatches the kind from `headerData/submissionType`, and
extracts the issuer block and kind-specific presence signals for
review. 

## Contracts

- **Native XML passes through**: a primary matching the family
  schema spec is returned byte-identical.
- **No lossy rebuild**: a payload that does not match the spec is
  refused, never rebuilt from the partial review model — the model
  deliberately covers header, issuer, and kind signals, not every
  offering and financial element.
- **Kinds come from the header only**: the form code on the filing
  index never overrides `headerData/submissionType`.

## Deliberate gaps

- **Offering and financial detail stay in the payload**: review
  records their presence and headline amounts; full offering /
  annual-report element modeling is not attempted.
- **No text-era conversion**: Form C has always been XML.
