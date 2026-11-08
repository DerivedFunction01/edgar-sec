"""SEC data-set download URL construction.

Per-vintage data-set ZIPs and the BDC report CSVs under the SEC files
base; a vintage label is refused when it is path-like.
"""

from __future__ import annotations

from edgar_sec.domain.sec_urls import SEC_DATASETS_BASE


def _dataset_vintage(vintage: str) -> str:
    """Return a dataset vintage label, refusing anything path-like."""
    label = str(vintage).strip()
    if not label or "/" in label or "\\" in label or label.startswith("."):
        raise ValueError(f"invalid dataset vintage: {vintage!r}")
    return label


def bdc_dataset_url(vintage: str) -> str:
    """Return the BDC data-set ZIP URL for one vintage label."""
    return (
        f"{SEC_DATASETS_BASE}/datastandardsinnovation/data/"
        f"business-development-company-bdc-data-sets/{_dataset_vintage(vintage)}_bdc.zip"
    )


def nmfp_dataset_url(vintage: str) -> str:
    """Return the Form N-MFP data-set ZIP URL for one vintage label."""
    return (
        f"{SEC_DATASETS_BASE}/dera/data/form-n-mfp-data-sets/"
        f"{_dataset_vintage(vintage)}_nmfp.zip"
    )


def mfrr_dataset_url(vintage: str) -> str:
    """Return the MFRR data-set ZIP URL for one vintage label."""
    return (
        f"{SEC_DATASETS_BASE}/dera/data/mutual-fund-prospectus-risk/"
        f"return-summary-data-sets/{_dataset_vintage(vintage)}_rr1.zip"
    )


def bdc_report_url(year: int) -> str:
    """Return the SEC BDC Report CSV URL for one report year."""
    if not 2000 <= int(year) <= 2100:
        raise ValueError(f"BDC report year out of range: {year!r}")
    return (
        f"{SEC_DATASETS_BASE}/investment/data/other/"
        f"business-development-company-report/business-development-company-{int(year)}.csv"
    )


__all__ = [
    "bdc_dataset_url",
    "bdc_report_url",
    "mfrr_dataset_url",
    "nmfp_dataset_url",
]
