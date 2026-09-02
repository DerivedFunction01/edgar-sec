"""Form-family evidence packs for shared SEC processing.

Submodules are intentionally not imported eagerly. Cover and table modules may
load these definitions during package initialization, so eager re-exports would
create a circular import through the public cover package.
"""

__all__: list[str] = []
