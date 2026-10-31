# EDGAR Ownership XML Technical Specification (Forms 3, 4, 5)

<!-- SENTINEL: XML_SCHEMAS -->

## 3. XML SCHEMAS

This section summarizes the restrictions and constraints imposed on the content of the six Ownership submission types (Forms 3, 3/A, 4, 4/A, 5, and 5/A). These rules are enforced by the schema files and by EDGAR submission processing applications.

The schema files cannot enforce all the rules concerning data content, so it is possible for a submission to satisfy all the schema constraints and still be **SUSPENDED** or **BLOCKED** by EDGAR.

### 3.1 Schema Table Column Definitions

The following defines the columns in the two schema summation tables provided in Sections 3.4 and 3.5:

#### Table 3-1: Column Definitions for Tables in Sections 3.4 and 3.5

| Column Name      | Description                                                                                                              |
| :--------------- | :----------------------------------------------------------------------------------------------------------------------- |
| **Level**        | Depth of element in the XML node hierarchy                                                                               |
| **Order**        | Order in which elements must appear                                                                                      |
| **Data Type**    | See the Data Type Constraints table for a detailed description                                                           |
| **Element Name** | Name of the XML element. This is case-sensitive                                                                          |
| **Max Length**   | Maximum length for String fields. EDGAR database stores up to this number of characters                                  |
| **Choice List**  | This name refers to a list of valid values for this field. The Choice List Values section provides the valid value lists |
| **Max Occur**    | Maximum times a set of elements may be repeated                                                                          |
| **3**            | Indicates applicability of this field to this submission type                                                            |
| **3/A**          | Indicates applicability of this field to this submission type                                                            |
| **4**            | Indicates applicability of this field to this submission type                                                            |
| **4/A**          | Indicates applicability of this field to this submission type                                                            |
| **5**            | Indicates applicability of this field to this submission type                                                            |
| **5/A**          | Indicates applicability of this field to this submission type                                                            |

### 3.2 Data Type Constraints

Each entry in the "Data Type" column of these tables will be one of these values:

| Data Type     | Constraints                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| :------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **boolean**   | Indicate a "true" value with either a `1` or the word `true`.<br>Indicate a "false" value with either a `0` or the word `false`.<br>A boolean element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error.                                                                                                                                                                                                                                                                                                                                                                          |
| **date**      | Must be of the format `YYYY-MM-DD`. A date element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error. Do not include a date element at all if your goal is to not provide an optional date.                                                                                                                                                                                                                                                                                                                                                                                       |
| **decimal**   | Only valid characters are `0-9` and a period. Cannot contain commas, a minus sign, a dollar sign, or parentheses. EDGAR stores up to four decimal places.<br>A decimal element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error. Do not include a decimal element at all if your goal is to not provide an optional number.<br>• Minimum allowable value = `0.0`<br>• Maximum allowable value = `999999999999.9999`                                                                                                                                                              |
| **string**    | Should be no longer than the length shown in the tables in Sections 3.4 and 3.5. EDGAR stores values in the `<footnote>`, `<signatureName>`, and `<contactEmailAddress>` elements exactly as provided. All other values are stored in the database as uppercase.<br>You must use special escape sequences to represent these four characters:<br>• For the `<` character use the escape sequence `<` or `&#60;`.<br>• For the `>` character use the escape sequence `>` or `&#62;`.<br>• For the `&` character use the escape sequence `&amp;` or `&#38;`.<br>• For the `"` character use the escape sequence `&quot;` or `&#34;`. |
| **ID, IDREF** | Used for linking footnotes to data fields. Must start with a capital `F`, which must be followed by a number from `1` to `99`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **NV**        | These fields cannot have a value. They are parent element nodes that contain other XML elements. These elements need to be present for proper validation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

### 3.3 Applicability of Schema Elements

Each entry in the six submission/document types columns in the tables in Sections 3.4 and 3.5 will have one of these values:

|    Value    | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| :---------: | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|    **m**    | Mandatory                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
|   **cm**    | Conditional Mandatory. The element is mandatory if its parent element is included. The element cannot be included if its parent is not included. This basic rule applies to next eight rows that detail additional "Conditional Mandatory" rules.                                                                                                                                                                                                                                                                                   |
|  **cm(1)**  | For the `<reportingOwnerRelationship>` group, at least one of the four boolean child elements must be true.                                                                                                                                                                                                                                                                                                                                                                                                                         |
|  **cm(2)**  | If `<reportingOwnerRelationship.isOfficer>` is true, then `<officerTitle>` becomes mandatory.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|  **cm(3)**  | If `<reportingOwnerRelationship.isOther>` is true, then `<otherText>` becomes mandatory.                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|  **cm(4)**  | If the conditional mandatory `<transactionAmounts>` group is used for a `<derivativeTransaction>`, you must provide a value for either `<transactionShares>` or `<transactionTotalValue>`. You cannot provide a value for both.                                                                                                                                                                                                                                                                                                     |
|  **cm(5)**  | If the value of `<directOrIndirectOwnership>` is `"D"`, do not supply a `<ownershipNature.natureOfOwnership>` value. You may either include the tag element with no data value or not include the tag element at all. If you supply a value for the tag element, the submission will be suspended.<br>If the value of `<directOrIndirectOwnership>` is `"I"`, `<ownershipNature.natureOfOwnership>` is mandatory. The submission will be suspended if the tag element is not included or the value of the tag element has no value. |
|  **cm(6)**  | In the mandatory `<underlyingSecurity>` group, you must provide a value for either `<underlyingSecurityShares>` or `<underlyingSecurityValue>`. You cannot provide a value for both.                                                                                                                                                                                                                                                                                                                                                |
|  **cm(7)**  | In the mandatory `<postTransactionAmounts>` group, you must provide a value for either `<sharesOwnedFollowingTransaction>` or `<valueOwnedFollowingTransaction>`. You cannot provide a value for both.                                                                                                                                                                                                                                                                                                                              |
|  **cm(8)**  | If nothing is provided for the `<value>`, then the element must be footnoted.                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
|  **cm(9)**  | If `<reportingOwnerAddress>` tag is provided then `<rptOwnerNonUSAddressFlag>` is mandatory.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **cm(10)**  | If `<reportingOwnerAddress.rptOwnerNonUSAddressFlag>` is true, then `<rptOwnerCountry>` becomes mandatory.                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **cm(11)**  | If `<reportingOwnerAddress.rptOwnerNonUSAddressFlag>` is false, then `<rptOwnerState>` becomes mandatory.                                                                                                                                                                                                                                                                                                                                                                                                                           |
|    **o**    | Optional                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|  **o(1)**   | The `<reportingOwner.rptOwnerCcc>` is optional in the schemas, but it is truly mandatory for input processing. It is marked as optional so that the CCC can be removed from the version of the document that is disseminated. In this way, the disseminated document will still conform to this specification.                                                                                                                                                                                                                      |
|   **NA**    | Does not apply to submission type. EDGAR uses this field for server-side processing. Do not provide a value for this element.                                                                                                                                                                                                                                                                                                                                                                                                       |
|  **(\*)**   | The maximum total number of transactions and/or holdings reported on a form may not exceed 60. The total number of rows in the Non-Derivative Table (Table 1 on the printed form) cannot exceed 30. This would include both `<nonDerivativeTransaction>` and `<nonDerivativeHolding>` entries. The total number of rows in the Derivative Table (Table 2 on the printed form) cannot exceed 30. This would include both `<derivativeTransaction>` and `<derivativeHolding>` entries.                                                |
| **_blank_** | Does not apply to submission type.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

<!-- SENTINEL: OWNERSHIP_SUBMISSION_SCHEMAS -->

### 3.4 Mapping of Ownership Submission Schemas to Submission Types

| Level | Order | Data Type | Element Name             | Max Length | Choice List  | Max Occur |  3  | 3/A |  4  | 4/A |  5  | 5/A |
| :---: | :---: | :-------- | :----------------------- | ---------: | :----------- | :-------: | :-: | :-: | :-: | :-: | :-: | :-: |
|   1   |   1   | NV        | edgarSubmission          |            |              |           |  m  |  m  |  m  |  m  |  m  |  m  |
|   2   |   1   | string    | submissionType           |          3 | SubTypeList  |           |  m  |  m  |  m  |  m  |  m  |  m  |
|   2   |   2   | string    | testOrLive               |          4 | TestLiveList |           |  m  |  m  |  m  |  m  |  m  |  m  |
|   2   |   3   | NV        | pointOfContact           |            |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   3   |   1   | string    | contactName              |         30 |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   3   |   2   | string    | contactPhoneNumber       |         20 |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   3   |   3   | string    | contactEmailAddress      |         80 |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   2   |   4   | NV        | notificationAddresses    |            |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   3   |   1   | string    | notificationEmailAddress |         80 |              |    30     |  o  |  o  |  o  |  o  |  o  |  o  |
|   2   |   6   | NV        | edgarDocument            |            |              |    611    |  m  |  m  |  m  |  m  |  m  |  m  |
|   3   |   1   | string    | documentName             |         32 |              |           |  m  |  m  |  m  |  m  |  m  |  m  |
|   3   |   2   | string    | documentType             |         20 | DocTypeList  |           |  m  |  m  |  m  |  m  |  m  |  m  |
|   3   |   3   | string    | documentDescription      |        255 |              |           |  o  |  o  |  o  |  o  |  o  |  o  |
|   3   |   4   | string    | documentMimeBlock        |  unlimited |              |           |  m  |  m  |  m  |  m  |  m  |  m  |

<!-- SENTINEL: OWNERSHIP_DOCUMENT_SCHEMAS -->

### 3.5 Mapping of Ownership Document Schemas to Document Types

| Level | Order | Data Type | Element Name                    | Max Length | Choice List      | Max Occur |    3    |   3/A   |    4    |   4/A   |    5    |   5/A   |
| :---: | :---: | :-------- | :------------------------------ | ---------: | :--------------- | :-------: | :-----: | :-----: | :-----: | :-----: | :-----: | :-----: |
|   1   |   1   | NV        | ownershipDocument               |            |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   2   |   1   | string    | schemaVersion                   |          5 |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   2   |   2   | string    | documentType                    |          3 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   2   |   3   | date      | periodOfReport                  |         10 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   2   |   4   | date      | dateOfOriginalSubmission        |         10 |                  |           |         |    m    |         |    m    |         |    m    |
|   2   |   5   | boolean   | noSecuritiesOwned               |            |                  |           |   NA    |   NA    |         |         |         |         |
|   2   |   6   | boolean   | notSubjectToSection16           |            |                  |           |         |         |    o    |    o    |    o    |    o    |
|   2   |   7   | boolean   | form3HoldingsReported           |            |                  |           |         |         |         |         |   NA    |   NA    |
|   2   |   8   | boolean   | form4TransactionsReported       |            |                  |           |         |         |         |         |   NA    |   NA    |
|   2   |   9   | NV        | issuer                          |            |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   1   | string    | issuerCik                       |         10 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   2   | string    | issuerName                      |        150 |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   3   |   3   | string    | issuerTradingSymbol             |         10 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   4   | string    | issuerForeignTradingSymbol      |         14 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   2   |  10   | NV        | reportingOwner                  |            |                  |    10     |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   1   | NV        | reportingOwnerId                |            |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   4   |   1   | string    | rptOwnerCik                     |         10 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   4   |   2   | string    | rptOwnerCcc                     |          8 |                  |           |  o(1)   |  o(1)   |  o(1)   |  o(1)   |  o(1)   |  o(1)   |
|   4   |   3   | string    | rptOwnerName                    |        150 |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   3   |   2   | NV        | reportingOwnerAddress           |            |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   1   | boolean   | rptOwnerNonUSAddressFlag        |            |                  |           |  cm(9)  |  cm(9)  |  cm(9)  |  cm(9)  |  cm(9)  |  cm(9)  |
|   4   |   2   | string    | rptOwnerStreet1                 |         40 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   3   | string    | rptOwnerStreet2                 |         40 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   4   | string    | rptOwnerCity                    |         30 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   5   | string    | rptOwnerNonUSStateTerritory     |         30 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   6   | string    | rptOwnerState                   |          2 | StateCodeList    |           | cm(10)  | cm(10)  | cm(10)  | cm(10)  | cm(10)  | cm(10)  |
|   4   |   7   | string    | rptOwnerCountry                 |          2 | CountryCode List |           | cm(11)  | cm(11)  | cm(11)  | cm(11)  | cm(11)  | cm(11)  |
|   4   |   8   | string    | rptOwnerZipCode                 |         10 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   9   | String    | rptOwnerStateDescription        |         50 |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   4   |  10   | boolean   | rptOwnerGoodAddress             |            |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   3   |   3   | NV        | reportingOwnerRelationship      |            |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   4   |   1   | boolean   | isDirector                      |            |                  |           |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |
|   4   |   2   | boolean   | isOfficer                       |            |                  |           |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |
|   4   |   3   | boolean   | isTenPercentOwner               |            |                  |           |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |
|   4   |   4   | boolean   | isOther                         |            |                  |           |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |  cm(1)  |
|   4   |   5   | string    | officerTitle                    |         30 |                  |           |  cm(2)  |  cm(2)  |  cm(2)  |  cm(2)  |  cm(2)  |  cm(2)  |
|   4   |   6   | string    | otherText                       |         30 |                  |           |  cm(3)  |  cm(3)  |  cm(3)  |  cm(3)  |  cm(3)  |  cm(3)  |
|   2   |  11   | boolean   | aff10b5One                      |            |                  |           |   NA    |   NA    |   NA    |   NA    |   NA    |   NA    |
|   2   |  12   | NV        | nonDerivativeTable              |            |                  |           |    o    |    o    |    R    |    R    |    R    |    R    |
|   3   |   1   | NV        | nonDerivativeTransaction        |            |                  |  30(\*)   |         |         |    o    |    o    |    o    |    o    |
|   4   |   1   | NV        | securityTitle                   |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | value                           |         60 |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   2   | NV        | transactionDate                 |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   3   | NV        | deemedExecutionDate             |            |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   4   | NV        | transactionCoding               |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | transactionFormType             |          1 | FormTypeList     |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | string    | transactionCode                 |          1 | TransCodeLi st   |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   3   | boolean   | equitySwapInvolved              |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   4   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   5   | NV        | transactionTimeliness           |            |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   1   | string    | value                           |          1 | TimelinessList   |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |         |         |
|   4   |   6   | NV        | transactionAmounts              |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | transactionShares               |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | NV        | transactionPricePerShare        |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   3   | NV        | transactionAcquiredDisposedCode |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | AcqDispList      |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   7   | NV        | postTransactionAmounts          |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | sharesOwnedFollowingTransaction |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | valueOwnedFollowingTransaction  |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   8   | NV        | ownershipNature                 |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | directOrIndirectOwnership       |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | OwnerTypeList    |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | natureOfOwnership               |            |                  |           |         |         |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   1   | string    | value                           |        100 |                  |           |         |         |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   3   |   2   | NV        | nonDerivativeHolding            |            |                  |  30(\*)   |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   1   | NV        | securityTitle                   |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | value                           |         60 |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   2   | NV        | transactionCoding               |            |                  |           |         |         |         |         |   cm    |   cm    |
|   5   |   1   | string    | transactionFormType             |          1 | FormTypeList     |           |         |         |         |         |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |         |         |    o    |    o    |
|   4   |   3   | NV        | postTransactionAmounts          |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | sharesOwnedFollowingTransaction |            |                  |           |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | valueOwnedFollowingTransaction  |            |                  |           |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   4   | NV        | ownershipNature                 |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | directOrIndirectOwnership       |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | OwnerTypeList    |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | natureOfOwnership               |            |                  |           |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   1   | string    | value                           |        100 |                  |           |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   2   |  13   | NV        | derivativeTable                 |            |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   3   |   1   | NV        | derivativeTransaction           |            |                  |  30(\*)   |         |         |    o    |    o    |    o    |    o    |
|   4   |   1   | NV        | securityTitle                   |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | value                           |         60 |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   2   | NV        | conversionOrExercisePrice       |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   3   | NV        | transactionDate                 |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   4   | NV        | deemedExecutionDate             |            |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   5   | NV        | transactionCoding               |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | transactionFormType             |          1 | FormTypeList     |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | string    | transactionCode                 |          1 | TransCodeLi st   |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   3   | boolean   | equitySwapInvolved              |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   4   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   6   | NV        | transactionTimeliness           |            |                  |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   1   | string    | value                           |          1 | TimelinessList   |           |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |         |         |
|   4   |   7   | NV        | transactionAmounts              |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | transactionShares               |            |                  |           |         |         |  cm(4)  |  cm(4)  |  cm(4)  |  cm(4)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(4)  |  cm(4)  |  cm(4)  |  cm(4)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | transactionTotalValue           |            |                  |           |         |         |  cm(4)  |  cm(4)  |  cm(4)  |  cm(4)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(4)  |  cm(4)  |  cm(4)  |  cm(4)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   3   | NV        | transactionPricePerShare        |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   4   | NV        | transactionAcquiredDisposedCode |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | AcqDispList      |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   4   |   8   | NV        | exerciseDate                    |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   9   | NV        | expirationDate                  |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |  10   | NV        | underlyingSecurity              |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | underlyingSecurityTitle         |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |         60 |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | underlyingSecurityShares        |            |                  |           |         |         | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   3   | NV        | underlyingSecurityValue         |            |                  |           |         |         | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |  11   | NV        | postTransactionAmounts          |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | sharesOwnedFollowingTransaction |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | valueOwnedFollowingTransaction  |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |  12   | NV        | ownershipNature                 |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | directOrIndirectOwnership       |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | OwnerTypeList    |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | natureOfOwnership               |            |                  |           |         |         |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   1   | string    | value                           |        100 |                  |           |         |         |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   3   |   1   | NV        | derivativeHolding               |            |                  |  30(\*)   |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   1   | NV        | securityTitle                   |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | string    | value                           |         60 |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   4   |   2   | NV        | conversionOrExercisePrice       |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | decimal   | value                           |            |                  |           |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   3   | NV        | transactionCoding               |            |                  |           |         |         |         |         |   cm    |   cm    |
|   5   |   1   | boolean   | transactionFormType             |          1 | FormTypeList     |           |         |         |         |         |   cm    |   cm    |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |         |         |    o    |    o    |
|   4   |   4   | NV        | exerciseDate                    |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   5   | NV        | expirationDate                  |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | date      | value                           |         10 |                  |           |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   2   | IDREF     | footnoteId                      |            |                  |    99     |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   6   | NV        | underlyingSecurity              |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | underlyingSecurityTitle         |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |         60 |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   2   | NV        | underlyingSecurityShares        |            |                  |           | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   1   | decimal   | value                           |            |                  |           | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   5   |   3   | NV        | underlyingSecurityValue         |            |                  |           | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   1   | decimal   | value                           |            |                  |           | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) | cm(6,8) |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |  cm(8)  |
|   4   |   7   | NV        | postTransactionAmounts          |            |                  |           |         |         |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | sharesOwnedFollowingTransaction |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | valueOwnedFollowingTransaction  |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   1   | decimal   | value                           |            |                  |           |         |         |  cm(7)  |  cm(7)  |  cm(7)  |  cm(7)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |         |         |    o    |    o    |    o    |    o    |
|   4   |   8   | NV        | ownershipNature                 |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   5   |   1   | NV        | directOrIndirectOwnership       |            |                  |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   1   | string    | value                           |          1 | OwnerTypeList    |           |   cm    |   cm    |   cm    |   cm    |   cm    |   cm    |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   5   |   2   | NV        | natureOfOwnership               |            |                  |           |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   1   | string    | value                           |        100 |                  |           |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |  cm(5)  |
|   6   |   2   | IDREF     | footnoteId                      |            |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   2   |  14   | NV        | footnotes                       |            |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   3   |   1   | string    | footnote                        |       1000 |                  |    99     |    o    |    o    |    o    |    o    |    o    |    o    |
|   2   |  15   | string    | remarks                         |       2000 |                  |           |    o    |    o    |    o    |    o    |    o    |    o    |
|   2   |  16   | NV        | ownerSignature                  |            |                  |    10     |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   1   | string    | signatureName                   |        255 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |
|   3   |   2   | date      | signatureDate                   |         10 |                  |           |    m    |    m    |    m    |    m    |    m    |    m    |

<!-- SENTINEL: CHOICE_LIST_VALUES -->

### 3.6 Choice List Values

#### 3.6.1 AcqDispList

These are the valid values for a `<transactionAcquiredDisposedCode>` element in the primary document:

| Value | Meaning  |
| :---: | :------- |
| **A** | Acquired |
| **D** | Disposed |

#### 3.6.2 CountryCodeList

EDGAR recognizes 253 two-character designators for the `<rptOwnerCountry>` element in the primary document. These are provided in Appendix H. These codes are the permissible values for the Canadian Provinces, and other countries and territories.

#### 3.6.3 DocTypeList

This list, which is actually a combination of two sets of values, defines the valid entries for a `<edgarDocument.documentType>` element in the submission file.

The `<documentType>` of the primary document must match the submission type, so it must be one of these values:

| Value for Primary Document |
| :------------------------: |
|            `3`             |
|           `3/A`            |
|            `4`             |
|           `4/A`            |
|            `5`             |
|           `5/A`            |

The `<documentType>` of a supporting document must be one of these values:

| Value for Supporting Document |
| :---------------------------- |
| `CORRESP`                     |
| `COVER`                       |
| `EX-24`                       |
| `EX-99`                       |
| `GRAPHIC`                     |

You can actually append optional text to these DocType values. This optional text must begin with a period. The overall length of the DocType value cannot exceed 20 characters. Some examples of a valid DocType are:

- `COVER.i_wrote_this`
- `COVER.1`
- `EX-99.myExhibit`

#### 3.6.4 FormTypeList

These are the valid values for a `<transactionFormType>` element in the primary document:

| Submission Type | Transaction Value | Holding Value |
| :-------------: | :---------------: | :-----------: |
|   **4, 4/A**    |       4, 5        |   _(blank)_   |
|   **5, 5/A**    |       4, 5        |       3       |

- You can report a "5" `<derivativeTransaction>` or `<nonDerivativeTransaction>` via a "4" submission.
- You can report a "4" `<derivativeTransaction>` or `<nonDerivativeTransaction>` transaction via a "5" submission.
- You can report a "3" `<derivativeHolding>` or `<nonDerivativeHolding>` via a "5" submission.

#### 3.6.5 OwnerTypeList

These are the valid values for a `<directOrIndirectOwnership>` element in the primary document:

| Value | Meaning  |
| :---: | :------- |
| **D** | Direct   |
| **I** | Indirect |

#### 3.6.6 StateCodeList

EDGAR recognizes 56 two-character designators for the `<rptOwnerState>` element in the primary document. These are provided in Appendix A. These codes are actually a combination of values for the 50 US states and 6 territories.

#### 3.6.7 SubTypeList

These are the valid values for the `<submissionType>` element in the submission document and the `<documentType>` element in the primary document:

| Value |
| :---: |
|  `3`  |
| `3/A` |
|  `4`  |
| `4/A` |
|  `5`  |
| `5/A` |

#### 3.6.8 TestLiveList

These are the valid values for the `<testOrLive>` element in the submission file:

| Value  |
| :----: |
| `LIVE` |
| `TEST` |

#### 3.6.9 TimelinessList

These are the valid values for a `<transactionTimeliness>` element in the primary document:

|   Value   | Meaning |
| :-------: | :------ |
|   **E**   | Early   |
|   **L**   | Late    |
| _(empty)_ | On-time |

#### 3.6.10 TransCodeList

These are the valid values for a `<transactionCode>` element in the primary document:

| Value | Meaning                                                                                                                                                                            |
| :---: | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A** | Grant, award or other acquisition pursuant to Rule 16b-3(d)                                                                                                                        |
| **C** | Conversion of derivative security                                                                                                                                                  |
| **D** | Disposition to the issuer of issuer equity securities pursuant to Rule 16b-3(e)                                                                                                    |
| **E** | Expiration of short derivative position                                                                                                                                            |
| **F** | Payment of exercise price or tax liability by delivering or withholding securities incident to the receipt, exercise or vesting of a security issued in accordance with Rule 16b-3 |
| **G** | Bona fide gift                                                                                                                                                                     |
| **H** | Expiration (or cancellation) of long derivative position with value received                                                                                                       |
| **I** | Discretionary transaction in accordance with Rule 16b-3(f) resulting in acquisition or disposition of issuer securities                                                            |
| **J** | Other acquisition or disposition (describe transaction)                                                                                                                            |
| **L** | Small acquisition under Rule 16a-6                                                                                                                                                 |
| **M** | Exercise or conversion of derivative security exempted pursuant to Rule 16b-3                                                                                                      |
| **O** | Exercise of out-of-the-money derivative security                                                                                                                                   |
| **P** | Open market or private purchase of non-derivative or derivative security                                                                                                           |
| **S** | Open market or private sale of non-derivative or derivative security                                                                                                               |
| **U** | Disposition pursuant to a tender of shares in a change of control transaction                                                                                                      |
| **W** | Acquisition or disposition by will or the laws of descent and distribution                                                                                                         |
| **X** | Exercise of in-the-money or at-the-money derivative security                                                                                                                       |
| **Z** | Deposit into or withdrawal from voting trust                                                                                                                                       |
