import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.ownership.schema import ownership_schema_anomalies


def test_ownership_schema_choice_checks() -> None:
    root = ET.fromstring(
        """<ownershipDocument>
          <documentType>4</documentType>
          <reportingOwner><reportingOwnerAddress>
            <rptOwnerState>ZZ</rptOwnerState>
          </reportingOwnerAddress></reportingOwner>
          <nonDerivativeTable><nonDerivativeTransaction>
            <transactionCoding><transactionCode>K</transactionCode>
              <transactionFormType>3</transactionFormType></transactionCoding>
            <transactionAmounts><transactionAcquiredDisposedCode><value>X</value>
            </transactionAcquiredDisposedCode></transactionAmounts>
          </nonDerivativeTransaction></nonDerivativeTable>
        </ownershipDocument>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000007")

    assert {item["kind"] for item in anomalies} == {
        "invalid_rptOwnerState",
        "invalid_transactionAcquiredDisposedCode",
        "invalid_transactionFormType",
        "invalid_transaction_code",
        "missing_non_us_address_flag",
    }


def test_confirmed_conditional_rules_when_fields_apply() -> None:
    root = ET.fromstring(
        """<ownershipDocument><documentType>5</documentType>
          <reportingOwner><reportingOwnerRelationship>
            <isDirector>1</isDirector><isOfficer>1</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner><isOther>1</isOther>
            <officerTitle>Director</officerTitle><otherText>Trustee</otherText>
          </reportingOwnerRelationship><reportingOwnerAddress>
            <rptOwnerNonUSAddressFlag>0</rptOwnerNonUSAddressFlag>
            <rptOwnerState>CA</rptOwnerState>
          </reportingOwnerAddress></reportingOwner>
          <derivativeTable><derivativeTransaction>
            <transactionAmounts><transactionShares><value>10</value></transactionShares>
            </transactionAmounts>
            <underlyingSecurity><underlyingSecurityShares><value>10</value>
            </underlyingSecurityShares></underlyingSecurity>
            <postTransactionAmounts><sharesOwnedFollowingTransaction><value>20</value>
            </sharesOwnedFollowingTransaction></postTransactionAmounts>
            <ownershipNature><directOrIndirectOwnership><value>D</value>
            </directOrIndirectOwnership></ownershipNature>
            <ownershipNature><directOrIndirectOwnership><value>I</value>
            </directOrIndirectOwnership><natureOfOwnership><value>Family trust</value>
            </natureOfOwnership></ownershipNature>
          </derivativeTransaction></derivativeTable>
          <derivativeTable><derivativeHolding><securityTitle><value>Option</value>
          </securityTitle></derivativeHolding></derivativeTable>
        </ownershipDocument>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000008")

    assert not {
        item["kind"]
        for item in anomalies
        if item["kind"].startswith(("missing_", "invalid_cm", "nature_for_"))
    }


def test_confirmed_conditional_rules_report_applicable_gaps() -> None:
    root = ET.fromstring(
        """<ownershipDocument><documentType>4</documentType>
          <reportingOwner><reportingOwnerRelationship>
            <isDirector>0</isDirector><isOfficer>1</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner><isOther>1</isOther>
          </reportingOwnerRelationship><reportingOwnerAddress/>
          <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>0</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther>
          </reportingOwnerRelationship>
          <reportingOwnerAddress><rptOwnerNonUSAddressFlag>1</rptOwnerNonUSAddressFlag>
          </reportingOwnerAddress><reportingOwnerAddress>
            <rptOwnerNonUSAddressFlag>0</rptOwnerNonUSAddressFlag>
          </reportingOwnerAddress></reportingOwner>
          <derivativeTable><derivativeTransaction>
            <transactionAmounts><transactionShares><value>1</value></transactionShares>
              <transactionTotalValue><value>1</value></transactionTotalValue>
            </transactionAmounts>
            <underlyingSecurity><underlyingSecurityShares><value>1</value>
              </underlyingSecurityShares><underlyingSecurityValue><value>1</value>
              </underlyingSecurityValue></underlyingSecurity>
            <postTransactionAmounts><sharesOwnedFollowingTransaction><value>1</value>
              </sharesOwnedFollowingTransaction><valueOwnedFollowingTransaction>
              <value>1</value></valueOwnedFollowingTransaction></postTransactionAmounts>
            <ownershipNature><directOrIndirectOwnership><value>D</value>
              </directOrIndirectOwnership><natureOfOwnership><value>Trust</value>
              </natureOfOwnership></ownershipNature>
            <ownershipNature><directOrIndirectOwnership><value>I</value>
              </directOrIndirectOwnership></ownershipNature>
            <securityTitle><value/><footnoteId id="f1"/></securityTitle>
            <securityTitle><value/></securityTitle>
          </derivativeTransaction></derivativeTable>
        </ownershipDocument>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000009")

    assert {
        "relationship_no_true_role",
        "missing_officer_title",
        "missing_other_text",
        "invalid_cm4_transaction_amount_values",
        "nature_for_direct_ownership",
        "missing_indirect_ownership_nature",
        "invalid_cm6_underlying_security_values",
        "invalid_cm7_post_transaction_amount_values",
        "unfootnoted_empty_value",
        "missing_non_us_address_flag",
        "missing_non_us_owner_country",
        "missing_us_owner_state",
    }.issubset({item["kind"] for item in anomalies}), {
        item["kind"] for item in anomalies
    }


def test_decimal_limits_and_amendment_date_applicability() -> None:
    root = ET.fromstring(
        """<ownershipDocument><documentType>4/A</documentType>
          <nonDerivativeTransaction><transactionAmounts>
            <transactionShares><value>1.23456</value></transactionShares>
            <transactionPricePerShare><value>-1</value></transactionPricePerShare>
            <transactionTotalValue><value>1000000000000</value></transactionTotalValue>
          </transactionAmounts></nonDerivativeTransaction>
        </ownershipDocument>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000011")
    kinds = {item["kind"] for item in anomalies}

    assert "missing_date_of_original_submission" in kinds
    assert "invalid_transactionShares_decimal" in kinds
    assert "invalid_transactionPricePerShare_decimal" in kinds
    assert "invalid_transactionTotalValue_decimal" in kinds


def test_schema_applies_singleton_cardinality_to_ownership_fields() -> None:
    root = ET.fromstring(
        """<ownershipDocument>
          <documentType>4</documentType>
          <documentType>4</documentType>
          <periodOfReport>2024-01-31</periodOfReport>
        </ownershipDocument>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000012")

    assert "excess_documentType" in {item["kind"] for item in anomalies}


def test_schema_does_not_apply_ownership_rules_to_other_families() -> None:
    root = ET.fromstring(
        """<edgarSubmission><headerData><submissionType>144</submissionType>
          </headerData><formData><issuerInfo><issuerName>Acme</issuerName>
          </issuerInfo></formData></edgarSubmission>"""
    )

    anomalies = ownership_schema_anomalies(root, "0001-01-000013")

    assert not {
        item["kind"]
        for item in anomalies
        if item["kind"].startswith(("invalid_", "excess_"))
    }
