"""Document storage pipeline: acquire, normalize, snapshot, consolidate.

Acquisition depends on the engine's SGML unpacker, so this package sits in
Layer 4 rather than ``infra``: a fetcher that has to call the engine cannot live
below it. The payload store it reads *is* infrastructure and stays in
``infra/storage/payload_store.py``.
"""
