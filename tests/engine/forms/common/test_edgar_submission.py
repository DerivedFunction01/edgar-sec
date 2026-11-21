from __future__ import annotations

from edgar_sec.engine.forms.common.edgar_submission import parse_edgar_header

_SUBMISSION = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/formc"
                 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>C-AR</submissionType>
    <filerInfo>
      <filer>
        <filerCredentials>
          <filerCik>0001161291</filerCik>
          <filerCcc>XXXXXXXX</filerCcc>
        </filerCredentials>
      </filer>
      <liveTestFlag>LIVE</liveTestFlag>
      <contact>
        <contactName>Steven</contactName>
        <contactEmail>zhangzhe@sec.gov</contactEmail>
      </contact>
    </filerInfo>
  </headerData>
  <formData/>
</edgarSubmission>
"""


def test_parse_header_extracts_type_filer_and_contact() -> None:
    header = parse_edgar_header(_SUBMISSION)
    assert header is not None
    assert header.submission_type == "C-AR"
    assert header.live_test_flag == "LIVE"
    assert header.filer_ciks == ("0001161291",)
    assert header.contact_name == "Steven"
    assert header.contact_email == "zhangzhe@sec.gov"


def test_parse_header_rejects_non_submission() -> None:
    assert parse_edgar_header(b"<notificationOfRemoval/>") is None
    assert parse_edgar_header(b"plain text") is None
