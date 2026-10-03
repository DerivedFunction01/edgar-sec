"""Layer 0 SQL primitives: a validator for operator-supplied queries.

The repository's own SQL is compiled or built from validated identifiers by
``infra.storage.duckdb`` and the pipeline/engine query modules; those paths do
not need a guard. What needs one is a *human typing a query*, where the string
is untrusted and the intent is unknown. That is the only case this package
serves.
"""
