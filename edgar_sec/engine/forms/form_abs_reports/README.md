# form_abs_reports

Engine machinery for the ABS text reports: Form 10-D asset-backed
issuer distribution reports and Form ABS-15G securitizer reports.
Layer 3 (engine), consuming the `form_abs_reports` domain package and
the shared cover machinery.

## Purpose

Reviews the two faces on one analyzer under the canonical `ABS`
family: the 10-D's rigid distribution cover (issuing entity,
depositor, and sponsor file numbers and CIKs, distribution period)
with its Part I / Part II item body, and the ABS-15G securitizer
cover with the Rule 15Ga-1 / 15Ga-2 obligation pair, its Part I
representation-and-warranty tables, and Part II Item 2.01.

## Contracts

- **Kind dispatch is by the filing's own form code**: distribution
  and securitizer share the analyzer but keep separate field sets
  and anomaly vocabularies.
- **Continuation parts are classified, not failed**: the ABS-15G/A
  population is dominated by multi-part filings whose later parts
  are bare representation-and-warranty tables with no cover; the
  analyzer records them as table fragments and raises no cover
  anomalies for them.
- **EX-102 / EX-103 companions stay with the exhibits machinery**:
  asset-data exhibits on 10-D hosts are the `form_abs_ee` companion
  scope; this package records the review's exhibit assessment but
  never parses asset data.

## Deliberate gaps

- **Part I table contents are not modeled**: the
  representation-and-warranty tables are recorded by header presence
  and shape, not row-extracted; loan-level demand data belongs to a
  future ABS data product, not this scope.
