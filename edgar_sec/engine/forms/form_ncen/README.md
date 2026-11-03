# form_ncen

SEC Form N-CEN annual report processing for registered investment companies
(Layer 3: Engine).

## Purpose

Provides native XML pass-through, XML parsing of the `edgarSubmission`
registrant identity core (name, file number, CIK, LEI, classification,
directors) into typed domain models, canonical XML rendering through the
shared builder, and semantic review analysis against the v3.1 technical
specification.

## Contracts

- **Byte-Identical Native Pass-Through**: Submissions conforming to the
  official N-CEN XML technical specification (v3.1) pass through with byte
  identity via `passthrough_sec_xml` against `N_CEN_XML_SPEC`.
- **Identity Core Extraction**: The typed model carries the registrant
  identity and service-provider counts; the questionnaire body is preserved
  by pass-through, never summarised into invented fields.

## Deliberate gaps

- **Questionnaire sections**: The management/UIT question series and
  attachments tab are pass-through only; no typed extraction is attempted.
- **Service-provider detail**: Custodian and pricing-service records are
  counted, not modelled; their names ride pass-through.
