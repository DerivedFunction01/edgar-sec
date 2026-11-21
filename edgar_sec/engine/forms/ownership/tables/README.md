# `edgar_sec.engine.forms.ownership.tables` — Table I / Table II construction

Builds the ownership Table I (non-derivative) and Table II (derivative) rows,
plus the reporting-owner relationship box, over the shared table core.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Relationship box parsing | [relationship_box.py](relationship_box.py) |
| Shared cell and row machinery | [table_common.py](table_common.py) |
| Table I rows | [table_i.py](table_i.py) |
| Table II rows | [table_ii.py](table_ii.py) |

## Contracts

- Columns are declared once as row specs in `ownership.specs` and normalized
  through the shared field contract, per the package contract.
- Table cells are mapped by lexical type invariants rather than rigid column
  coordinates.

## Deliberate gaps

- Form 3 table layouts beyond the supported holding layouts stay in the
  sidecar, per the package's gaps.
