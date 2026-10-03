"""Document storage pipeline: acquire, normalize, snapshot, consolidate.

Acquisition depends on the engine's SGML unpacker, so this package sits in
Layer 4 rather than ``infra``: a fetcher that has to call the engine cannot live
below it. The raw-payload fixture store it reads is owned here too, in
``fixture_store.py``.
"""
