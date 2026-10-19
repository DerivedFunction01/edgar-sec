"""Tests for Form 144 review analysis and summarizer."""

from pathlib import Path
import tempfile

from edgar_sec.engine.forms.form144.analysis import analyze_case, summarize_cases
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership">
  <headerData>
    <submissionType>144</submissionType>
    <filerInfo>
      <filer><filerCredentials><cik>0000000001</cik><ccc>12345678</ccc></filerCredentials></filer>
      <liveTestFlag>LIVE</liveTestFlag>
      <contact><contactName>Review Contact</contactName><contactPhone>555-555-5555</contactPhone><contactEmail>review@example.com</contactEmail></contact>
      <flags />
    </filerInfo>
  </headerData>
  <formData>
    <issuerInfo>
      <issuerCik>0000000002</issuerCik>
      <issuerName>Gamma Corp</issuerName>
      <issuerAddress><street1>1 Main Street</street1><city>Boston</city><stateOrCountry>MA</stateOrCountry><zipCode>02110</zipCode></issuerAddress>
      <issuerContactPhone>555-555-1111</issuerContactPhone>
      <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Alice Green</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
      <relationshipsToIssuer><relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer>
    </issuerInfo>
    <securitiesInformation>
      <securitiesClassTitle>Common Stock</securitiesClassTitle>
      <brokerOrMarketmakerDetails><name>Example Broker</name><address><street1>2 Broad Street</street1><city>Boston</city><stateOrCountry>MA</stateOrCountry><zipCode>02110</zipCode></address></brokerOrMarketmakerDetails>
      <noOfUnitsSold>2500</noOfUnitsSold>
      <aggregateMarketValue>50000.00</aggregateMarketValue>
      <noOfUnitsOutstanding>100000</noOfUnitsOutstanding>
      <approxSaleDate>06-01-2023</approxSaleDate>
      <securitiesExchangeName>NASDAQ</securitiesExchangeName>
    </securitiesInformation>
    <securitiesToBeSold><securitiesClassTitle>Common Stock</securitiesClassTitle><acquiredDate>01-01-2022</acquiredDate><natureOfAcquisitionTransaction>Open market purchase</natureOfAcquisitionTransaction><isGiftTransaction>N</isGiftTransaction><amountOfSecuritiesAcquired>2500</amountOfSecuritiesAcquired><natureOfPayment>Cash</natureOfPayment></securitiesToBeSold>
    <nothingToReportFlagOnSecuritiesSoldInPast3Months>Y</nothingToReportFlagOnSecuritiesSoldInPast3Months>
    <noticeSignature>
      <planAdoptionDates><planAdoptionDate>01-15-2023</planAdoptionDate></planAdoptionDates>
      <noticeDate>06-01-2023</noticeDate>
      <signature>/s/ Alice Green</signature>
    </noticeSignature>
  </formData>
  <unparsedSections>
    <unparsedSection tableIndex="4" role="unparsed">Table I trailing data</unparsedSection>
  </unparsedSections>
</edgarSubmission>
"""


def test_analyze_and_summarize_case():
    with tempfile.TemporaryDirectory() as tmp_dir:
        case_dir = Path(tmp_dir) / "cases" / "0000000001-23-000001"
        ops_dir = case_dir / "operations"
        ops_dir.mkdir(parents=True)
        xml_file = ops_dir / "render_to_xml.xml"
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")

        record = {"accession": "0000000001-23-000001"}
        case_rep = analyze_case(case_dir, record)
        assert case_rep is not None
        assert case_rep["error"] is None
        assert case_rep["core_fields"]["issuerName"] is True
        assert case_rep["core_fields"]["noOfUnitsSold"] is True
        assert len(case_rep["anomalies"]) == 0
        assert len(case_rep["review_signals"]) == 1
        assert case_rep["unparsed_section_count"] == 1
        assert case_rep["unparsed_sections"][0]["table_index"] == 4

        summary = summarize_cases([case_rep])
        assert summary["family"] == "144"
        assert summary["case_count"] == 1
        assert summary["anomaly_count"] == 0
        assert summary["review_signal_count"] == 1
        assert summary["unparsed_section_count"] == 1
        assert summary["substantive_unparsed_count"] == 1
        assert summary["value_frequencies"]["exchange"]["distinct_values"] == 1
        assert (
            summary["value_frequencies"]["exchange"]["top_values"][0]["value"]
            == "NASDAQ"
        )


def test_analyze_case_loads_unparsed_sidecar():
    with tempfile.TemporaryDirectory() as tmp_dir:
        case_dir = Path(tmp_dir) / "cases" / "0000000001-23-000001"
        ops_dir = case_dir / "operations"
        ops_dir.mkdir(parents=True)
        (ops_dir / "render_to_xml.xml").write_text(SAMPLE_XML, encoding="utf-8")
        sidecar = serialize_unparsed_sections(
            [
                {
                    "role": "unparsed",
                    "content_type": "text/html",
                    "content": "<table><tr><td>Review this retained table</td></tr></table>",
                    "table_index": 7,
                }
            ]
        )
        (ops_dir / "unparsed_sections.json").write_bytes(sidecar)

        result = analyze_case(case_dir, {"accession": "0000000001-23-000001"})
        assert result is not None
        assert result["unparsed_section_count"] == 1
        assert result["unparsed_sections"][0]["table_index"] == 7
        assert "Review this retained table" in result["unparsed_sections"][0]["snippet"]


def test_schema_conditional_requirements_follow_reported_flags():
    with tempfile.TemporaryDirectory() as tmp_dir:
        case_dir = Path(tmp_dir) / "cases" / "conditional"
        ops_dir = case_dir / "operations"
        ops_dir.mkdir(parents=True)
        xml_path = ops_dir / "render_to_xml.xml"

        xml_path.write_text(
            SAMPLE_XML.replace(
                "<nothingToReportFlagOnSecuritiesSoldInPast3Months>Y</nothingToReportFlagOnSecuritiesSoldInPast3Months>",
                "<nothingToReportFlagOnSecuritiesSoldInPast3Months>N</nothingToReportFlagOnSecuritiesSoldInPast3Months>",
            ),
            encoding="utf-8",
        )
        no_sales = analyze_case(case_dir, {"accession": "conditional"})
        assert no_sales is not None
        assert "missing_schema_securitiesSoldInPast3Months" in {
            item["kind"] for item in no_sales["anomalies"]
        }

        xml_path.write_text(
            SAMPLE_XML.replace(
                "<submissionType>144</submissionType>",
                "<submissionType>144/A</submissionType>",
            ),
            encoding="utf-8",
        )
        amendment = analyze_case(case_dir, {"accession": "conditional"})
        assert amendment is not None
        assert "missing_schema_previousAccessionNumber" in {
            item["kind"] for item in amendment["anomalies"]
        }
