"""Shared Feed test fixtures: listings, SGML bundles, and tarballs."""

from __future__ import annotations

import io
import tarfile
from datetime import date


def listing_html(*filenames: str) -> str:
    """A Feed directory listing page naming each file once as an href."""
    rows = "\n".join(f'<a href="{name}">{name}</a>' for name in filenames)
    return f"<html><body>\n{rows}\n</body></html>"


def sgml_bundle(
    *,
    accession: str = "0000320193-24-000001",
    cik: int = 320193,
    form: str = "10-K",
    filed: date = date(2024, 1, 2),
) -> bytes:
    """One SGML bundle whose SEC header carries the given fields."""
    header = (
        "<SEC-DOCUMENT>\n<SEC-HEADER>\n"
        f"ACCESSION NUMBER:\t\t{accession}\n"
        f"CONFORMED SUBMISSION TYPE:\t{form}\n"
        f"FILED AS OF DATE:\t\t{filed:%Y%m%d}\n"
        "FILER:\n"
        f"CENTRAL INDEX KEY:\t\t{cik:010d}\n"
        "</SEC-HEADER>\n</SEC-DOCUMENT>\n"
    )
    return header.encode()


def feed_tarball(members: dict[str, bytes]) -> bytes:
    """A gzipped Feed tarball holding each named member's bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def sgml_nc_bundle(
    *,
    accession: str = "0000110471-25-000125",
    cik: int = 110471,
    form: str = "10-Q",
    filed: date = date(2025, 8, 7),
) -> bytes:
    """One Feed ``.nc`` bundle: an SGML tag-value header, CR-separated."""
    lines = [
        "<SUBMISSION>",
        f"<ACCESSION-NUMBER>{accession}",
        f"<TYPE>{form}",
        "<PUBLIC-DOCUMENT-COUNT>1",
        f"<FILING-DATE>{filed:%Y%m%d}",
        "<FILER>",
        "<COMPANY-DATA>",
        f"<CIK>{cik:010d}",
    ]
    return ("\r".join(lines) + "\r").encode()
