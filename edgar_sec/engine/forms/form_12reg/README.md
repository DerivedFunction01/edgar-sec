# form_12reg

Engine machinery for the Section 12 registration cluster: issuer
Form 25 removal notifications, Form 8-A Section 12 registrations,
and Form 8-B successor-issuer registrations (the predecessor-era
variant). Layer 3 (engine), consuming the `form_12reg` domain
package and the shared cover machinery.

## Purpose

Reviews the three faces on one analyzer: the 25's short notice face
with its Rule 12d2-2 X-box block, and the 8-A / 8-B registration
covers with the class-of-securities / exchange table and the
two-item statement body.

## Contracts

- **Kind dispatch is by the filing's own form code**: notification,
  registration, and predecessor registration share the analyzer but
  keep separate field sets and anomaly vocabularies.
- **Cover fields come from the cover region** the shared boundary
  machinery resolves; the class table is read as consecutive
  class/exchange line pairs under its column header.

## Deliberate gaps

- **Paper-segment Form 25 filings stay raw-only**: the 412
  paper-era rows carry no renderable primary by nature and are not
  fixture targets.
