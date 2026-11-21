# `edgar_sec.engine.forms.ownership.ascii` — ASCII table route

The plain-text route of the ownership package: filings whose tables arrive as
ASCII text rather than markup are classified and extracted here.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Header block parsing | [ascii_header.py](ascii_header.py) |
| Whole-document ASCII parse | [ascii_parser.py](ascii_parser.py) |
| Table shape classification | [ascii_shape.py](ascii_shape.py) |
| Table extraction from text | [ascii_tables.py](ascii_tables.py) |

## Contracts

- Consumes classified sections from the package root (`sections`) and yields
  the same table shapes the markup route produces.
- Pure transformation only, per the package contract: total, offline, no I/O.

## Deliberate gaps

- No paper or PDF text extraction runs here; that deferral is the package's.
