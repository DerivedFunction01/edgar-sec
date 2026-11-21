# `edgar_sec.pipelines.metadata_sync.reference` — Series/Class Reference Leg

The fund series/class reference leg: the mutual-fund ticker file's full
rows and the browse-edgar series pages publish as one two-layer DAG
relation beside the metadata snapshots.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Tickered layer and combined publication | [series_class.py](series_class.py) |
| Browse-edgar series page layer | [series_class_browse.py](series_class_browse.py) |

## Contracts

- The tickered layer republishes the MF ticker file's rows field-for-field;
  the browse layer adds series and class names and un-tickered classes.
- Both layers publish together through the DAG in the family's own
  snapshots root.
- A series page that does not parse exactly contributes nothing.

## Deliberate Gaps

- Zero-tickered-class registrants are unserved: a registrant whose classes
  all lack tickers never enters the browse drive's population.
- Neither layer carries an LEI — the ticker file and the series pages do
  not serve one.
