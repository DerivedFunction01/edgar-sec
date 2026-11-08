# earnings

Earnings-exhibit extraction in the current-report family (Layer 3, `engine/forms`).

## Purpose

Given a current-report filing and its EX-99 exhibits, this package selects the
earnings exhibit, structures its financial tables through the table-geometry
machinery behind `normalize_document`, and reads the headline figures
(revenue, net income, EPS as presented) from those tables. Scope per class was
set by the Step 6 specimen corpus record: HTML statement exhibits extract
deterministically; text-class exhibits, no-statement HTML exhibits, and 6-K
headline figures are review signals; image exhibits are refused.

## Contracts

- **Selection is filename-family-based only**: modern `ex[-_]?99`, `exhibit[-_]?99`, `exh[-_]?99`, and agent-mangled `exv99w<digits>` families, ordered by exhibit number then filename. The filing index `type` field is an icon token and is never consulted.
- **EX-99.1 is tried first**; when it carries no income statement, later EX-99 exhibits are tried in order and the fallback is recorded as a review signal.
- **Filename selection proposes; the exhibit evaluator confirms**: a `possible_role_mismatch` disposition from `evaluate_exhibit_body` (excluding the 99.x sub-number artifact) refuses extraction from that exhibit and surfaces as a review signal.
- **PDF exhibits ride the document-processing PDF route** (`convert_pdf_to_text`, embedded text layer only); the converted text joins the text class. Raw PDF bytes never enter `normalize_document`.
- **Every unextracted table is accounted**: fallback geometries, prose-borne headlines, and unstructureable exhibits each produce a named review signal with its specimen class; nothing is silently dropped or best-effort parsed.
- **No EX-99 exhibit is honest absence**: the result carries `absence_reason="no_ex99_exhibit"` and no exhibit.
- **Table indices are exhibit-local positions**: `table_index` counts the exhibit's geometries in order, matching the corpus record's inventory numbering; the geometry machinery's own index is not served.
- **Numeric recognition is the shared forms vocabulary**: cell recognition goes through `engine/forms/common/numbers.py` (`clean_numeric`, built on the schema numeric tokens and currency token handling), as with the XML family processors; values are still served exactly as printed.
- **Table roles stay lane-local by measurement**: a 2026-11-08 comparison over the Step 6 corpus (1,136 tables) scored the shared table-taxonomy classifier far below the lane heuristics on earnings exhibits (balance-sheet recall 3/81, 114 income-statement false positives, 7 headline components lost downstream), so roles are assigned by this package's heuristics; the classifier is not wired in. Record: `.artifacts/run-logs/2026-11-08-table-taxonomy-measurement.md`.

## Deliberate gaps

- **No prose headline extraction**: figures that live only in prose are review signals, not extraction targets.
- **No 6-K headline figures**: 6-K tables extract, but their headline figures await the IFRS label vocabulary owned by the 6-K taxonomy work.
- **No OCR**: image exhibits are inventoried only.
- **No inline-XBRL exhibit handling**: the corpus observed none, so no behaviour is designed for that class.
