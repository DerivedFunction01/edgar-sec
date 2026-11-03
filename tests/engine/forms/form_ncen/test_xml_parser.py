"""Tests for the Form N-CEN XML parser."""

from edgar_sec.engine.forms.form_ncen.xml_parser import parse_ncen_xml

_SUBMISSION = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ncen">
  <headerData>
    <submissionType>N-CEN</submissionType>
    <filerInfo>
      <filer><issuerCredentials><cik>0000123456</cik></issuerCredentials></filer>
      <investmentCompanyType>N-2</investmentCompanyType>
    </filerInfo>
  </headerData>
  <formData>
    <generalInfo/>
    <registrantInfo>
      <registrantFullName>ACME INCOME FUND</registrantFullName>
      <investmentCompFileNo>811-00000</investmentCompFileNo>
      <registrantCik>0000123456</registrantCik>
      <registrantLei>549300K6JNPNZMSWMF07</registrantLei>
      <registrantcity>Boston</registrantcity>
      <registrantstate>US-MA</registrantstate>
      <registrantcountry>US</registrantcountry>
      <isRegistrantFirstFiling>N</isRegistrantFirstFiling>
      <isRegistrantLastFiling>N</isRegistrantLastFiling>
      <registrantClassificationType>N-2</registrantClassificationType>
      <directors>
        <director><directorName>JANE DOE</directorName></director>
        <director><directorName>JOHN ROE</directorName></director>
      </directors>
      <securityMatterSeriesInfo>
        <seriesInfo><seriesName>ACME SERIES</seriesName></seriesInfo>
      </securityMatterSeriesInfo>
    </registrantInfo>
  </formData>
</edgarSubmission>
"""


def test_parse_ncen_submission() -> None:
    """Registrant identity, directors, and counts parse into the model."""
    doc = parse_ncen_xml(_SUBMISSION)
    assert doc.submission_type == "N-CEN"
    assert doc.registrant_name == "ACME INCOME FUND"
    assert doc.file_number == "811-00000"
    assert doc.classification_type == "N-2"
    assert doc.directors == ("JANE DOE", "JOHN ROE")
    assert doc.series_count == 1
    assert doc.filer_cik == "0000123456"
