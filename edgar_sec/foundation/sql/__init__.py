"""Layer 0 SQL primitives: a validator for operator-supplied queries.

Only a string a *human typed* needs a guard; queries built from validated identifiers by
``infra.storage.duckdb`` do not.
"""
