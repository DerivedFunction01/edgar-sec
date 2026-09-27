"""Quarterly report (Form 10-Q) normalization pipeline."""

from __future__ import annotations

from .common import ProfileDrivenPipeline


class QuarterlyPipeline(ProfileDrivenPipeline):
    """Normalization pipeline for Quarterly Reports (10-Q family)."""

    def __init__(self, family: str = "10-Q") -> None:
        super().__init__(family=family, enable_toc=False, enable_body_start=True)


__all__ = ["QuarterlyPipeline"]
