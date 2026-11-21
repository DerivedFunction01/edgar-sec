# form_nport

SEC Form N-PORT registered fund portfolio reporting (Layer 3: Engine).

## Purpose

Provides native XML pass-through, XML parsing of the `edgarSubmission`
general/fund information and the `invstOrSecs` schedule of investments into
typed domain models, canonical XML rendering through the shared builder, and
semantic review analysis against the v1.13 technical specification.

## Contracts

- **Byte-Identical Native Pass-Through**: Submissions conforming to the
  official N-PORT XML technical specification (v1.13) pass through with byte
  identity via `passthrough_sec_xml` against `NPORT_XML_SPEC`.
- **Decimal Fidelity**: Monetary and percentage values are carried as the
  filed decimal strings; no float conversion occurs at parse or render time.
- **Attribute-Carried Identifiers**: The ISIN rides the `identifiers/isin`
  element's `value` attribute and the currency on `currencyConditional`'s
  `curCd` attribute; both survive the canonical render.

## Deliberate gaps

- **Fund information tail**: Return/flow detail inside `fundInfo` beyond the
  three balance totals is preserved by pass-through but not typed.
- **Derivative and lending detail**: Per-investment sub-blocks (debt terms,
  derivatives, securities lending) ride pass-through unmodelled.
