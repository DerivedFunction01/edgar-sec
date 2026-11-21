# EDGAR Form 144 XML Technical Specification

<!-- SENTINEL: XML_SCHEMAS -->

## 3 XML SCHEMAS

This section summarizes the restrictions and constraints imposed on the content of the Form 144 submission types. These rules are enforced by the schema files and by EDGAR submission processing applications.

The schema files cannot enforce all the rules concerning data content, so it is possible for a submission to satisfy all the schema constraints and still be **SUSPENDED** or **BLOCKED** by EDGAR.

### 3.1 Schema Table Column Definitions

The following table defines the columns in the schema summation table provided in Section 3.4:

#### Table 3-1: Column Definitions for the Tables in Section 3-4

| Column Name                  | Description                                                                                                                                                                                  |
| :--------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Level**                    | Depth of element in the XML node hierarchy.                                                                                                                                                  |
| **Order**                    | Order in which elements must appear.                                                                                                                                                         |
| **Data Type**                | See Table in Section 3.2 for a detailed description.                                                                                                                                         |
| **Element Name**             | Name of the XML element. This is case-sensitive.                                                                                                                                             |
| **Max Length**               | Maximum length for elements. EDGAR database stores up to this number of characters. "Unlimited" means no maximum length constraint for the element value.                                    |
| **Data Value Constraint**    | The paragraph that describes the data value constraint for the element. The values specified are case sensitive.                                                                             |
| **Max Occur**                | Maximum times a set of elements may be repeated. The maximum occurrence is 1, if not specified.                                                                                              |
| **Applicability of Element** | Indicates applicability of the element. `m` = Mandatory, `o` = Optional, `NA` = Does not apply. EDGAR uses this element for server-side processing. Do not provide a value for this element. |

### 3.2 Data Type Constraints

Each entry in the "Data Type" column of these tables will be one of these values:

| Data Type   | Constraints                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| :---------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Boolean** | Indicate a "true" value with either a `1` or the word `true`.<br>Indicate a "false" value with either a `0` or the word `false`.<br>A Boolean element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error.                                                                                                                                                                                                                                                                                                                                                |
| **date**    | Must be of the format `MM-DD-YYYY`. A date element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error. Do not include a date element at all if your goal is to not provide an optional date.                                                                                                                                                                                                                                                                                                                                                             |
| **integer** | Only valid characters are `0-9`. Cannot contain commas, a minus sign, a dollar sign, or parentheses.<br>An integer element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error.                                                                                                                                                                                                                                                                                                                                                                           |
| **string**  | Should be no longer than the length shown in the tables in Section 3.4.<br>EDGAR stores values in the `<signPersonName>`, and `<contactEmail>` elements exactly as provided. All other values are stored in the database as uppercase.<br>You must use special escape sequences to represent these four characters:<br>• For the `<` character use the escape sequence `<` or `&#60;`.<br>• For the `>` character use the escape sequence `>` or `&#62;`.<br>• For the `&` character use the escape sequence `&amp;` or `&#38;`.<br>• For the `"` character use the escape sequence `&quot;` or `&#34;`. |
| **NV**      | These fields cannot have a value. They are parent element nodes that contain other XML elements. These elements need to be present for proper validation.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **attr**    | Attribute property for an XML element.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

### 3.3 Applicability of Schema Elements

Each entry in the submission/document type column in Section 3.4 will have one of these values:

|    Value    | Description                                                                                                                                      |
| :---------: | :----------------------------------------------------------------------------------------------------------------------------------------------- |
|    **m**    | Mandatory                                                                                                                                        |
|   **m#**    | Conditional Mandatory. The element is mandatory if its parent element is included. The element cannot be included if its parent is not included. |
|   **m#1**   | Conditional Mandatory. The element is mandatory if specific values are provided for other elements.                                              |
|   **m#2**   | This element is required for correct processing of the submission type.                                                                          |
|    **o**    | Optional                                                                                                                                         |
|   **o#**    | Optional in the Schema. The value will be populated by EDGAR. Any value provided will be overwritten and a WARNING generated.                    |
|   **NA**    | Does not apply to submission type. EDGAR uses this field for server-side processing. Do not provide a value for this element.                    |
| **_blank_** | Does not apply to submission type.                                                                                                               |

<!-- SENTINEL: FORM_144_SCHEMA_MAPPING -->

### 3.4 Mapping of Form 144 Submission Schemas to Submission Types

#### Mapping of Form 144 and Variants Submission Schema to Submission Type

| Level | Order | Data Type | Element/Attribute Name                              | Max Length | Choice List             | Max Occur | 144 | 144/A |
| :---: | :---: | :-------- | :-------------------------------------------------- | ---------: | :---------------------- | :-------: | :-: | :---: |
|   1   |   1   | NV        | edgarSubmission                                     |            |                         |     1     |  m  |   m   |
|   2   |   1   | String    | schemaVersion                                       |          5 |                         |     1     |  o  |   o   |
|   2   |   2   | NV        | headerData                                          |            |                         |     1     |  m  |   m   |
|   3   |   1   | String    | submissionType                                      |            | SUBMISSION_TYPE         |     1     |  m  |   m   |
|   3   |   2   | String    | previousAccessionNumber                             |         20 |                         |     1     | NA  |   m   |
|   3   |   3   | NV        | filerInfo                                           |            |                         |     1     |  m  |   m   |
|   4   |   1   | NV        | filer                                               |            |                         |     1     |  m  |   m   |
|   5   |   1   | NV        | filerCredentials                                    |            |                         |     1     |  m  |   m   |
|   6   |   1   | String    | cik                                                 |         10 |                         |     1     |  m  |   m   |
|   6   |   2   | String    | ccc                                                 |          8 |                         |     1     |  m  |   m   |
|   4   |   2   | String    | liveTestFlag                                        |            | LIVE_TEST_TYPE          |     1     |  m  |   m   |
|   4   |   3   | NV        | contact                                             |            |                         |     1     |  m  |   m   |
|   5   |   1   | String    | contactName                                         |         30 |                         |     1     |  m  |   m   |
|   5   |   2   | String    | contactPhone                                        |         20 |                         |     1     |  m  |   m   |
|   5   |   3   | String    | contactEmail                                        |         80 |                         |     1     |  m  |   m   |
|   4   |   4   | NV        | flags                                               |            |                         |     1     |  m  |   m   |
|   5   |   1   | Boolean   | overrideInternetFlag                                |            | "true" or "false"       |     1     |  o  |   o   |
|   4   |   5   | NV        | notifications                                       |            |                         |     1     |  o  |   o   |
|   5   |   1   | String    | notificationEmail                                   |         80 |                         |     3     |  o  |   o   |
|   2   |   3   | NV        | formData                                            |            |                         |     1     |  m  |   m   |
|   3   |   1   | NV        | issuerInfo                                          |            |                         |     1     |  m  |   m   |
|   4   |   1   | String    | issuerCik                                           |         10 |                         |     1     |  m  |   m   |
|   4   |   2   | String    | issuerName                                          |        150 |                         |     1     |  m  |   m   |
|   4   |   3   | String    | secFileNumber                                       |            |                         |     1     |  o  |   o   |
|   4   |   4   | NV        | issuerAddress                                       |            |                         |     1     |  m  |   m   |
|   5   |   1   | String    | street1                                             |         40 |                         |     1     |  m  |   m   |
|   5   |   2   | String    | street2                                             |         40 |                         |     1     |  o  |   o   |
|   5   |   3   | String    | city                                                |         30 |                         |     1     |  m  |   m   |
|   5   |   4   | String    | stateOrCountry                                      |          2 |                         |     1     |  m  |   m   |
|   5   |   5   | String    | zipCode                                             |         10 |                         |     1     |  m  |   m   |
|   4   |   5   | String    | issuerContactPhone                                  |         20 |                         |     1     |  m  |   m   |
|   4   |   6   | String    | nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold |        150 |                         |     1     |  m  |   m   |
|   4   |   7   | NV        | relationshipsToIssuer                               |            |                         |     1     |  m  |   m   |
|   5   |   1   | String    | relationshipToIssuer                                |         50 | RELATIONSHIPS_TO_ISSUER |     5     |  m  |   m   |
|   3   |   2   | NV        | securitiesInformation                               |            |                         |    40     |  m  |   m   |
|   4   |   1   | String    | securitiesClassTitle                                |        150 |                         |     1     |  m  |   m   |
|   4   |   2   | NV        | brokerOrMarketmakerDetails                          |            |                         |     1     |  m  |   m   |
|   5   |   1   | String    | name                                                |        100 |                         |     1     |  m  |   m   |
|   5   |   2   | NV        | address                                             |            |                         |     1     |  m  |   m   |
|   6   |   1   | String    | street1                                             |         40 |                         |     1     |  m  |   m   |
|   6   |   2   | String    | street2                                             |         40 |                         |     1     |  o  |   o   |
|   6   |   3   | String    | city                                                |         30 |                         |     1     |  m  |   m   |
|   6   |   4   | String    | stateOrCountry                                      |          2 |                         |     1     |  m  |   m   |
|   6   |   5   | String    | zipCode                                             |         10 |                         |     1     |  m  |   m   |
|   4   |   3   | Integer   | noOfUnitsSold                                       |         12 |                         |     1     |  m  |   m   |
|   4   |   4   | Decimal   | aggregateMarketValue                                |         14 |                         |     1     |  m  |   m   |
|   4   |   5   | Integer   | noOfUnitsOutstanding                                |         12 |                         |     1     |  m  |   m   |
|   4   |   6   | Date      | approxSaleDate                                      |            |                         |     1     |  m  |   m   |
|   4   |   7   | String    | securitiesExchangeName                              |         20 |                         |     1     |  m  |   m   |
|   3   |   3   | NV        | securitiesToBeSold                                  |            |                         |    40     |  m  |   m   |
|   4   |   1   | String    | securitiesClassTitle                                |        150 |                         |     1     |  m  |   m   |
|   4   |   2   | Date      | acquiredDate                                        |            |                         |     1     |  m  |   m   |
|   4   |   3   | String    | natureOfAcquisitionTransaction                      |        255 |                         |     1     |  m  |   m   |
|   4   |   4   | String    | nameOfPersonfromWhomAcquired                        |        100 |                         |     1     | m#1 |  m#1  |
|   4   |   5   | String    | isGiftTransaction                                   |          1 | "Y" or "N'              |     1     |  m  |   m   |
|   4   |   6   | Date      | donarAcquiredDate                                   |            |                         |     1     | m#1 |  m#1  |
|   4   |   7   | Integer   | amountOfSecuritiesAcquired                          |         12 |                         |     1     |  m  |   m   |
|   4   |   8   | Date      | paymentDate                                         |            |                         |     1     | m#1 |  m#1  |
|   4   |   9   | String    | natureOfPayment                                     |        255 |                         |     1     |  m  |   m   |
|   3   |   4   | String    | nothingToReportFlagOnSecuritiesSoldInPast3Months    |            | "Y" or "N'              |     1     |  m  |   m   |
|   3   |   5   | NV        | securitiesSoldInPast3Months                         |            |                         |    200    | m#1 |  m#1  |
|   4   |   1   | NV        | sellerDetails                                       |            |                         |     1     | m#1 |  m#1  |
|   5   |   1   | String    | name                                                |        100 |                         |     1     | m#1 |  m#1  |
|   5   |   2   | NV        | address                                             |            |                         |     1     | m#1 |  m#1  |
|   6   |   1   | String    | street1                                             |         40 |                         |     1     | m#1 |  m#1  |
|   6   |   2   | String    | street2                                             |         40 |                         |     1     |  o  |   o   |
|   6   |   3   | String    | city                                                |         30 |                         |     1     | m#1 |  m#1  |
|   6   |   4   | String    | stateOrCountry                                      |          2 |                         |     1     | m#1 |  m#1  |
|   6   |   5   | String    | zipCode                                             |         10 |                         |     1     | m#1 |  m#1  |
|   4   |   2   | String    | securitiesClassTitle                                |        150 |                         |     1     | m#1 |  m#1  |
|   4   |   3   | Date      | saleDate                                            |            |                         |     1     | m#1 |  m#1  |
|   4   |   4   | Integer   | amountOfSecuritiesSold                              |         12 |                         |     1     | m#1 |  m#1  |
|   4   |   5   | Decimal   | grossProceeds                                       |         14 |                         |     1     | m#1 |  m#1  |
|   3   |   6   | String    | remarks                                             |       1000 |                         |     1     |  o  |   o   |
|   3   |   7   | NV        | noticeSignature                                     |            | NOTICE_SIGNATUTE        |     1     |  m  |   m   |
|   4   |   1   | Date      | noticeDate                                          |            |                         |     1     |  m  |   m   |
|   4   |   2   | NV        | planAdoptionDates                                   |            |                         |     1     |  o  |   o   |
|   5   |   1   | Date      | planAdoptionDate                                    |            |                         |    20     |  o  |   o   |
|   4   |   3   | String    | signature                                           |        150 |                         |     1     |  m  |   m   |
|   2   |   4   | NV        | documents                                           |            |                         |     1     | m#  |  m#   |
|   3   |   1   | NV        | document                                            |            |                         | unlimited | m#  |  m#   |
|   4   |   1   | String    | conformedName                                       |         32 |                         |     1     |  m  |   m   |
|   4   |   2   | String    | conformedDocumentType                               |            | SUB_DOCUMENT_TYPE       |     1     |  m  |   m   |
|   4   |   3   | String    | description                                         |        255 |                         |     1     |  o  |   o   |
|   4   |   4   | String    | contents                                            |            |                         |     1     |  m  |   m   |

<!-- SENTINEL: FORM_144_DATA_VALUE_CONSTRAINTS -->

## 4 144 SCHEMA DATA VALUE CONSTRAINTS

### 4.1 SUBMISSION_TYPE

These are the valid values for the `<SUBMISSION_TYPE>` element in the submission file:

| VALUE     | CODE DESCRIPTION                                     |
| :-------- | :--------------------------------------------------- |
| **144**   | Notice of Proposed Sale of Securities.               |
| **144/A** | Amendment to Notices of Proposed Sale of Securities. |

### 4.2 LIVE_TEST_TYPE

These are the valid values for the `<LIVE_TEST_TYPE>` element in the submission file:

| VALUE  |
| :----- |
| `LIVE` |
| `TEST` |

### 4.3 RELATIONSHIPS_TO_ISSUER

These are the valid values for the `<RELATIONSHIPS_TO_ISSUER>` element in the submission file:

| VALUE                                              |
| :------------------------------------------------- |
| Officer                                            |
| Director                                           |
| 10% Stockholder                                    |
| Member of immediate family of any of the foregoing |
| Provide any other relationship not mentioned above |
