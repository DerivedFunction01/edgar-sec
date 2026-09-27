"""Annual report (Form 10-K, 20-F) normalization pipeline."""

from __future__ import annotations

from .common import ProfileDrivenPipeline


class AnnualPipeline(ProfileDrivenPipeline):
    """Normalization pipeline for Annual Reports (10-K family, 20-F)."""

    def __init__(self, family: str = "10-K") -> None:
        super().__init__(family=family, enable_toc=True, enable_body_start=True)


__all__ = ["AnnualPipeline"]
