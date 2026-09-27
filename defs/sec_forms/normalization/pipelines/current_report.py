"""Current report (Form 8-K) normalization pipeline."""

from __future__ import annotations

from .common import ProfileDrivenPipeline


class CurrentReportPipeline(ProfileDrivenPipeline):
    """Normalization pipeline for Current Reports (8-K family)."""

    def __init__(self, family: str = "8-K") -> None:
        super().__init__(family=family, enable_toc=False, enable_body_start=False)


__all__ = ["CurrentReportPipeline"]
