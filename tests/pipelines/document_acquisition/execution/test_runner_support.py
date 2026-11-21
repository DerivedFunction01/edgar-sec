from __future__ import annotations

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.pipelines.document_acquisition.execution.runner_support import (
    validate_redirect,
)
from tests.pipelines.document_acquisition.execution.runner_fixtures import (
    ACCESSION as _ACCESSION,
    BUNDLE_URL as _BUNDLE_URL,
)


def test_redirect_validator_binds_to_requested_archive_cik() -> None:
    url = _BUNDLE_URL.replace("/320193/", "/320194/")

    validate_redirect(url, AccessionNumber(_ACCESSION), "320194")
    with pytest.raises(ValueError):
        validate_redirect(url, AccessionNumber(_ACCESSION), "320193")
