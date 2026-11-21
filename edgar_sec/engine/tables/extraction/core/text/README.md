# `edgar_sec.engine.tables.extraction.core.text` — Text Primitives

The text side of the extraction core: the table context model, text
normalization, note titles, period keys, placement facts, and signature
regions — the primitives every other extraction subpackage builds on.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Table context model | [context.py](context.py) |
| Text normalization | [normalize.py](normalize.py) |
| Note titles | [note_titles.py](note_titles.py) |
| Period keys | [period_keys.py](period_keys.py) |
| Placement facts | [placement.py](placement.py) |
| Signature regions | [regions.py](regions.py) |

## Contracts

- **Scale is data or explicit unknown**: a table's scale is a parsed
  `Scale` or `None`; no consumer re-derives it from rendered text.
- **Region is hard context** (`regions`): a geometry inside a signature
  region is never a statement candidate, whatever its vocabulary scores.

## Deliberate gaps

- No family knowledge lives here; profiles and vocabulary are owned by
  the sibling `subjects` group.
