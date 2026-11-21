# `edgar_sec.engine.forms.ownership.specs` — declarative specifications

The declarative layer of the ownership package: field specifications, the
Table I / Table II row specifications, and the SEC ownership schema checks.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Field specifications | [field_specs.py](field_specs.py) |
| Table row specifications | [row_specs.py](row_specs.py) |
| Schema anomalies | [schema.py](schema.py) |

## Contracts

- Specs are data, not behaviour: parsers and table builders consume them;
  nothing here parses a filing.
- Table I and Table II columns are declared once here and normalized through
  the shared field contract, per the package contract.

## Deliberate gaps

- Late-filing Box 1(b) flags are not modelled as distinct statutory flags,
  per the package's gaps.
