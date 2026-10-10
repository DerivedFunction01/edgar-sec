from edgar_sec.pipelines.document_acquisition.resolution import screen_sgml_type


def test_sgml_type_screen_requires_ascii_and_exact_form_identity() -> None:
    assert screen_sgml_type("10-K", "10-K") == "form_match"
    assert screen_sgml_type("10-k", "10-K") == "type_mismatch"
    assert screen_sgml_type("8-K", "10-K") == "type_mismatch"
    assert screen_sgml_type("10-Ké", "10-K") == "unverifiable"
    assert screen_sgml_type(None, "10-K") == "unverifiable"
