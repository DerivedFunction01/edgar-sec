"""Layer 3 engine: transformation of SEC payloads.

The transformation packages (``document``, ``tables``, ``reflow``, ``forms``,
``submissions``) are pure and side-effect-free. ``selection`` and
``company_family`` are the named exceptions: they materialize and read a
snapshot through ``infra/storage``. See ``edgar_sec/engine/README.md``.
"""
