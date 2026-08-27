"""Public API barrel for the metadata phase core.

Exports only the public application functions; entry points import from
here, not from individual implementation modules.
"""

from .application import (
    build_plan,
    get_status,
    load_plan,
    merge,
    preview_sample,
    run_chunk,
)
from .config import RunOptions
from .merge import MergeError

__all__ = [
    "MergeError",
    "RunOptions",
    "build_plan",
    "get_status",
    "load_plan",
    "merge",
    "preview_sample",
    "run_chunk",
]
