# `edgar_sec.engine.forms.ownership.parsers` — metadata parsers

Parses the filing-level metadata of an ownership document: the metadata block,
the reporting period, and the reporting owner's identity.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Filing metadata block | [metadata_parser.py](metadata_parser.py) |
| Reporting period dates | [period_parser.py](period_parser.py) |
| Reporting owner identity | [reporting_owner_parser.py](reporting_owner_parser.py) |

## Contracts

- Field shapes come from the declarative specs in `ownership.specs`; the
  relationship box comes from `ownership.tables`.
- Recognized values are normalized to ownership XML types and date format,
  per the package contract.

## Deliberate gaps

- Non-standard co-owner schedules stay unparsed here, per the package's gaps.
