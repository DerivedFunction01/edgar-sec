"""Contract tests for shared SEC HTTP request headers."""

import pytest

from defs.sec_http import default_headers


def test_headers_carry_identity_and_encoding_without_pinning_a_host():
    headers = default_headers("TestClient/1.0 test@example.com")
    assert headers["User-Agent"] == "TestClient/1.0 test@example.com"
    assert "Accept-Encoding" in headers
    # The client serves data.sec.gov and www.sec.gov; a pinned Host breaks the
    # other endpoint (archive requests 404ed under Host: data.sec.gov). The
    # HTTP library must derive Host from each request URL.
    assert "Host" not in {key.lower() for key in headers}


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "no-contact-info"],
)
def test_headers_reject_user_agents_without_a_contact_address(user_agent):
    with pytest.raises(ValueError):
        default_headers(user_agent)
