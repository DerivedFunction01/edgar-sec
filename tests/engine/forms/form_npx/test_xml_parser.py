"""Tests for the Form N-PX XML parser."""

from edgar_sec.engine.forms.form_npx.xml_parser import parse_npx_xml

_SUBMISSION = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/npx">
  <headerData>
    <submissionType>N-PX</submissionType>
    <filerInfo>
      <registrantType>RMIC</registrantType>
      <liveTestFlag>LIVE</liveTestFlag>
      <investmentCompanyType>N-2</investmentCompanyType>
      <periodOfReport>06/30/2025</periodOfReport>
    </filerInfo>
  </headerData>
  <formData>
    <coverPage>
      <yearOrQuarter>YEAR</yearOrQuarter>
      <reportCalendarYear>2025</reportCalendarYear>
      <reportingPerson><name>ACME FUND INC</name></reportingPerson>
      <reportInfo><reportType>FUND VOTING REPORT</reportType></reportInfo>
      <fileNumber>811-00000</fileNumber>
      <leiNumber>549300FH0LKMOBY7N332</leiNumber>
    </coverPage>
    <seriesPage><seriesCount>2</seriesCount></seriesPage>
  </formData>
</edgarSubmission>
"""

_VOTE_TABLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<inf:proxyVoteTable xmlns:inf="http://www.sec.gov/edgar/document/npxproxy/informationtable">
  <inf:proxyTable>
    <inf:issuerName>ACME CORP</inf:issuerName>
    <inf:cusip>001000000</inf:cusip>
    <inf:meetingDate>06/12/2025</inf:meetingDate>
    <inf:voteDescription>Election of directors</inf:voteDescription>
    <inf:voteCategories>
      <inf:voteCategory><inf:categoryType>DIRECTOR ELECTIONS</inf:categoryType>
      </inf:voteCategory>
    </inf:voteCategories>
    <inf:voteSource>ISSUER</inf:voteSource>
    <inf:sharesVoted>1000</inf:sharesVoted>
    <inf:vote>
      <inf:voteRecord><inf:howVoted>For</inf:howVoted></inf:voteRecord>
    </inf:vote>
  </inf:proxyTable>
</inf:proxyVoteTable>
"""


def test_parse_npx_cover() -> None:
    """Cover identity parses into the model with no vote rows."""
    doc = parse_npx_xml(_SUBMISSION)
    assert doc.submission_type == "N-PX"
    assert doc.registrant_type == "RMIC"
    assert doc.reporting_person_name == "ACME FUND INC"
    assert doc.report_type == "FUND VOTING REPORT"
    assert doc.file_number == "811-00000"
    assert doc.series_count == 2
    assert doc.vote_rows == ()


def test_parse_npx_vote_table() -> None:
    """A standalone vote table document parses its rows."""
    doc = parse_npx_xml(_VOTE_TABLE)
    assert doc.submission_type == ""
    assert len(doc.vote_rows) == 1
    row = doc.vote_rows[0]
    assert row.issuer_name == "ACME CORP"
    assert row.cusip == "001000000"
    assert row.category_types == ("DIRECTOR ELECTIONS",)
    assert row.how_voted == ("For",)
    assert row.shares_voted == "1000"
