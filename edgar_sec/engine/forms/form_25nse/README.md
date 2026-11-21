# form_25nse

Engine machinery for SEC Form 25-NSE, the exchange notification of
removal from listing and/or registration. Layer 3 (engine), consuming
the `form_25nse` domain models.

## Purpose

Parses the native XML document (root `notificationOfRemoval`, spec
v4.3) into the domain model, renders it through the XML handler
registry, and audits review cases field by field. Primaries filed as
a full `edgarSubmission` wrapper are read through to the embedded
notification block.

## Contracts

- **Native XML passes through**: a primary matching the family schema
  spec is returned byte-identical; only non-matching payloads are
  parsed and rebuilt canonically.
- **Both schema versions are accepted as filed**: X0203 (current) and
  X0202 documents parse through the same model; the version is
  recorded, never converted.
- **Parsing is namespace-tolerant**: elements match by local name, so
  wrapper and bare documents share one code path.

## Deliberate gaps

- **No text-era conversion**: the form has always been XML; there is
  no ASCII predecessor to convert from.
