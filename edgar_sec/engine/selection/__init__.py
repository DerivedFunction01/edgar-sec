"""Stratified selection engine: policy, features, candidate access, deficit fill.

Selection is the Stage B half of the filing-catalog pipeline. It answers a
question deterministic planning cannot: not "which rows match these four
filters" but "which rows best fill a declared quota profile, without letting
one corporate family or one form crowd out the rest".

The package is split on the pure/impure seam, the same split
``engine.company_family`` uses:

* :mod:`~edgar_sec.engine.selection.policy` -- the declarative policy model and
  its serialization. No artifact reads.
* :mod:`~edgar_sec.engine.selection.features` -- the feature snapshot builder.
  Reads catalog artifacts, writes the snapshot.
* :mod:`~edgar_sec.engine.selection.source` -- bounded, storage-backed candidate
  access. One DuckDB connection, one session.
* :mod:`~edgar_sec.engine.selection.selector` -- the five-phase deficit fill.
* :mod:`~edgar_sec.engine.selection.inventory` -- feasibility statistics.

Date-bound filtering and era stratification live *exclusively* in ``policy``.
"""
