"""Generic fallback normalization pipeline for unmodeled forms."""

from __future__ import annotations

from .common import ProfileDrivenPipeline


class FallbackPipeline(ProfileDrivenPipeline):
    """Fallback normalization pipeline for unspecified/generic forms."""

    def __init__(self, family: str = "GENERIC") -> None:
        super().__init__(family=family, enable_toc=False, enable_body_start=False)


__all__ = ["FallbackPipeline"]
