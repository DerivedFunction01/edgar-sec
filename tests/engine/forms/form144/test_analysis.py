"""Tests for Form 144 review analysis and summarizer."""

from pathlib import Path
import tempfile

from edgar_sec.engine.forms.form144.analysis import analyze_case, summarize_cases

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership">
  <formData>
    <issuerInfo>
      <issuerName>Gamma Corp</issuerName>
      <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Alice Green</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
      <relationshipsToIssuer><relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer>
    </issuerInfo>
    <securitiesInformation>
      <securitiesClassTitle>Common Stock</securitiesClassTitle>
      <noOfUnitsSold>2500</noOfUnitsSold>
      <aggregateMarketValue>50000.00</aggregateMarketValue>
      <approxSaleDate>06/01/2023</approxSaleDate>
      <securitiesExchangeName>NASDAQ</securitiesExchangeName>
    </securitiesInformation>
    <noticeSignature>
      <planAdoptionDates><planAdoptionDate>01/15/2023</planAdoptionDate></planAdoptionDates>
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
        assert case_rep["unparsed_sections"][0]["table_index"] == "4"

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
