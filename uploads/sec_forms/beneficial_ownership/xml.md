# EDGAR Schedule 13D and 13G XML Technical Specification

<!-- SENTINEL: XML_SCHEMAS -->

## 3 XML SCHEMAS

This section summarizes the restrictions and constraints imposed on the content of the Schedule 13D and 13G submission types. These rules are enforced by the schema files and by EDGAR submission processing applications.

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

| Data Type   | Constraints                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| :---------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Boolean** | Indicate a "true" value with either a `1` or the word `true`.<br>Indicate a "false" value with either a `0` or the word `false`.<br>A Boolean element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error.                                                                                                                                                                                                                                                                                                                                               |
| **date**    | Must be of the format `MM-DD-YYYY`. A date element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error. Do not include a date element at all if your goal is to not provide an optional date.                                                                                                                                                                                                                                                                                                                                                            |
| **integer** | Only valid characters are `0-9`. Cannot contain commas, a minus sign, a dollar sign, or parentheses.<br>An integer element may not have a null or blank value. This is a schema violation and will cause a **SUSPENSE** error.                                                                                                                                                                                                                                                                                                                                                                          |
| **string**  | Should be no longer than the length shown in the tables in Section 3.4.<br>EDGAR stores values in the `<signPersonName>` and `<contactEmail>` elements exactly as provided. All other values are stored in the database as uppercase.<br>You must use special escape sequences to represent these four characters:<br>• For the `<` character use the escape sequence `<` or `&#60;`.<br>• For the `>` character use the escape sequence `>` or `&#62;`.<br>• For the `&` character use the escape sequence `&amp;` or `&#38;`.<br>• For the `"` character use the escape sequence `&quot;` or `&#34;`. |
| **NV**      | These fields cannot have a value. They are parent element nodes that contain other XML elements. These elements need to be present for proper validation.                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **attr**    | Attribute property for an XML element.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

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

<!-- SENTINEL: SCHEDULE_13D_SCHEMA_MAPPING -->

### 3.4 Mapping of Schedule 13D Submission Schemas to Submission Types

| Level | Order | Data Type | Element/Attribute Name      | Max Length | Choice List              | Max Occur | SCHEDULE 13D | SCHEDULE 13D/A |
| :---: | :---: | :-------- | :-------------------------- | ---------: | :----------------------- | :-------: | :----------: | :------------: |
|   1   |   1   | NV        | edgarSubmission             |            |                          |     1     |      m       |       m        |
|   2   |   1   | String    | schemaVersion               |          5 |                          |     1     |      o       |       o        |
|   2   |   2   | NV        | headerData                  |            |                          |     1     |      m       |       m        |
|   3   |   1   | String    | submissionType              |            | SUBMISSION_TYPE          |     1     |      m       |       m        |
|   3   |   2   | String    | previousAccessionNumber     |         20 |                          |     1     |      NA      |       o        |
|   3   |   3   | NV        | filerInfo                   |            |                          |     1     |      m       |       m        |
|   4   |   1   | NV        | filer                       |            |                          |     1     |      m       |       m        |
|   5   |   1   | NV        | filerCredentials            |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | cik                         |         10 |                          |     1     |      m       |       m        |
|   6   |   2   | String    | ccc                         |          8 |                          |     1     |      m       |       m        |
|   4   |   2   | String    | liveTestFlag                |            | LIVE_TEST_TYPE           |     1     |      m       |       m        |
|   4   |   3   | NV        | flags                       |            |                          |     1     |      m       |       m        |
|   5   |   1   | Boolean   | overrideInternetFlag        |            | "true" or "false"        |     1     |      o       |       o        |
|   4   |   4   | NV        | contact                     |            |                          |     1     |      m       |       m        |
|   5   |   1   | String    | contactName                 |         30 |                          |     1     |      m       |       m        |
|   5   |   2   | String    | contactPhoneNumber          |         20 |                          |     1     |      m       |       m        |
|   5   |   3   | String    | contactEmailAddress         |         80 |                          |     1     |      m       |       m        |
|   4   |   5   | NV        | notifications               |            |                          |     1     |      o       |       o        |
|   5   |   1   | String    | notificationEmailAddress    |         80 |                          |     3     |      o       |       o        |
|   2   |   3   | NV        | formData                    |            |                          |     1     |      m       |       m        |
|   3   |   1   | NV        | coverPageHeader             |            |                          |     1     |      m       |       m        |
|   4   |   1   | String    | amendmentNo                 |          3 |                          |     1     |      NA      |       m        |
|   4   |   2   | String    | securitiesClassTitle        |        150 |                          |     1     |      m       |       m        |
|   4   |   3   | Date      | dateOfEvent                 |         17 |                          |     1     |      m       |       m        |
|   4   |   4   | String    | previouslyFiledFlag         |            | "true" or "false"        |     1     |      o       |       o        |
|   4   |   5   | NV        | issuerInfo                  |            |                          |     1     |      m       |       m        |
|   5   |   1   | String    | issuerCIK                   |         10 |                          |     1     |      m       |       m        |
|   5   |   2   | NV        | issuerCusips                |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | issuerCusipNumber           |         12 |                          |    20     |      m       |       m        |
|   5   |   3   | String    | issuerName                  |        150 |                          |     1     |     m#1      |      m#1       |
|   5   |   4   | NV        | address                     |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | street1                     |         40 |                          |     1     |      m       |       m        |
|   6   |   2   | String    | street2                     |         40 |                          |     1     |      o       |       o        |
|   6   |   3   | String    | city                        |         30 |                          |     1     |      m       |       m        |
|   6   |   4   | String    | stateOrCountry              |          2 |                          |     1     |      m       |       m        |
|   6   |   5   | String    | zipCode                     |         10 |                          |     1     |      m       |       m        |
|   4   |   6   | NV        | authorizedPersons           |         40 |                          |     1     |      o       |       o        |
|   5   |   1   | NV        | notificationInfo            |            |                          |    100    |      m       |       m        |
|   6   |   1   | String    | personName                  |         30 |                          |     1     |      m       |       m        |
|   6   |   2   | String    | personPhoneNum              |         20 |                          |     1     |      m       |       m        |
|   6   |   3   | NV        | personAddress               |            |                          |     1     |      m       |       m        |
|   7   |   1   | String    | street1                     |         40 |                          |     1     |      m       |       m        |
|   7   |   2   | String    | street2                     |         40 |                          |     1     |      o       |       o        |
|   7   |   3   | String    | city                        |         30 |                          |     1     |      m       |       m        |
|   7   |   4   | String    | stateOrCountry              |          2 |                          |     1     |      m       |       m        |
|   7   |   5   | String    | zipCode                     |         10 |                          |     1     |      m       |       m        |
|   3   |   2   | NV        | reportingPersons            |            |                          |     1     |      m       |       m        |
|   4   |   1   | NV        | reportingPersonInfo         |            |                          |    100    |      m       |       m        |
|   5   |   1   | String    | reportingPersonCIK          |         10 |                          |     1     |      o       |       o        |
|   5   |   2   | String    | reportingPersonNoCIK        |          1 | "Y" or "N'               |     1     |      o       |       o        |
|   5   |   3   | String    | reportingPersonName         |        150 |                          |     1     |      m       |       m        |
|   5   |   4   | String    | memberOfGroup               |          1 | MEMBER_TYPE              |     1     |      o       |       o        |
|   5   |   5   | String    | fundType                    |          2 | FUND_TYPE                |     6     |      m       |       o        |
|   5   |   6   | String    | legalProceedings            |          1 | "Y" or "N'               |     1     |      o       |       o        |
|   5   |   7   | String    | citizenshipOrOrganization   |          2 |                          |     1     |      m       |       o        |
|   5   |   8   | Decimal   | soleVotingPower             |         17 |                          |     1     |      m       |       o        |
|   5   |   9   | Decimal   | sharedVotingPower           |         17 |                          |     1     |      m       |       o        |
|   5   |  10   | Decimal   | soleDispositivePower        |         17 |                          |     1     |      m       |       o        |
|   5   |  11   | Decimal   | sharedDispositivePower      |         17 |                          |     1     |      m       |       o        |
|   5   |  12   | Decimal   | aggregateAmountOwned        |         17 |                          |     1     |      m       |       o        |
|   5   |  13   | String    | isAggregateExcludeShares    |          1 | "Y" or "N'               |     1     |      o       |       o        |
|   5   |  14   | Decimal   | percentOfClass              |          5 |                          |     1     |      m       |       o        |
|   5   |  15   | String    | typeOfReportingPerson       |          2 | TYPE_OF_REPORTING_PERSON |    13     |      m       |       o        |
|   5   |  16   | String    | commentContent              |      20000 |                          |     1     |      o       |       o        |
|   3   |   3   | NV        | items1To7                   |            |                          |     1     |      m       |       m        |
|   4   |   1   | NV        | item1                       |            |                          |     1     |      m       |       m        |
|   5   |   1   | String    | securityTitle               |        150 |                          |     1     |     m#1      |      m#1       |
|   5   |   2   | String    | issuerName                  |        150 |                          |     1     |     m#1      |      m#1       |
|   5   |   3   | NV        | issuerPrincipalAddress      |            |                          |     1     |     m#1      |      m#1       |
|   6   |   1   | String    | street1                     |         40 |                          |     1     |     m#1      |      m#1       |
|   6   |   2   | String    | street2                     |         40 |                          |     1     |      o       |       o        |
|   6   |   3   | String    | city                        |         30 |                          |     1     |     m#1      |      m#1       |
|   6   |   4   | String    | stateOrCountry              |          2 |                          |     1     |     m#1      |      m#1       |
|   6   |   5   | String    | zipCode                     |         10 |                          |     1     |     m#1      |      m#1       |
|   5   |   4   | String    | commentText                 |      20000 |                          |     1     |      o       |       o        |
|   4   |   2   | NV        | Item2                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | filingPersonName            |      20000 |                          |     1     |      m       |       o        |
|   5   |   2   | String    | principalBusinessAddress    |      20000 |                          |     1     |      m       |       o        |
|   5   |   3   | String    | principalJob                |      20000 |                          |     1     |      m       |       o        |
|   5   |   4   | String    | hasBeenConvicted            |      20000 |                          |     1     |      m       |       o        |
|   5   |   5   | String    | convictionDescription       |      20000 |                          |     1     |      m       |       o        |
|   5   |   6   | String    | citizenship                 |       2000 |                          |     1     |      m       |       o        |
|   4   |   3   | NV        | Item3                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | fundsSource                 |      20000 |                          |     1     |      m       |       o        |
|   4   |   4   | NV        | Item4                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | transactionPurpose          |      20000 |                          |     1     |      m       |       o        |
|   4   |   5   | NV        | Item5                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | percentageOfClassSecurities |      20000 |                          |     1     |      m       |       o        |
|   5   |   2   | String    | numberOfShares              |      20000 |                          |     1     |      m       |       o        |
|   5   |   3   | String    | transactionDesc             |      20000 |                          |     1     |      m       |       o        |
|   5   |   4   | String    | listOfShareholders          |      20000 |                          |     1     |      m       |       o        |
|   5   |   5   | String    | date5PercentOwnership       |      20000 |                          |     1     |      m       |       o        |
|   4   |   6   | NV        | Item6                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | contractDescription         |      20000 |                          |     1     |      m       |       o        |
|   4   |   7   | NV        | Item7                       |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | filedExhibits               |      20000 |                          |     1     |      o       |       o        |
|   3   |   4   | String    | signatureInfo               |            |                          |     1     |      m       |       m        |
|   4   |   1   | NV        | signaturePerson             |            |                          |    100    |      m       |       m        |
|   5   |   1   | String    | signatureReportingPerson    |        150 |                          |     1     |     m#1      |      m#1       |
|   6   |   1   | NV        | signatureDetails            |            |                          |    50     |      m       |       m        |
|   7   |   1   | String    | signature                   |        150 |                          |     1     |      m       |       m        |
|   7   |   2   | String    | title                       |        150 |                          |     1     |      m       |       m        |
|   7   |   3   | Date      | date                        |            |                          |     1     |      m       |       m        |
|   4   |   2   | String    | commentText                 |      20000 |                          |     1     |      o       |       o        |
|   2   |   4   | NV        | documents                   |            |                          |     1     |      o       |       o        |
|   3   |   1   | NV        | document                    |            |                          | unlimited |      o       |       o        |
|   4   |   1   | String    | conformedName               |         32 |                          |     1     |      o       |       o        |
|   4   |   2   | String    | conformedDocumentType       |            | SUB_DOCUMENT_TYPE        |     1     |      o       |       o        |
|   4   |   4   | String    | description                 |        255 |                          |     1     |      o       |       o        |
|   4   |   5   | String    | contents                    |            |                          |     1     |      o       |       o        |

<!-- SENTINEL: SCHEDULE_13G_SCHEMA_MAPPING -->

### 3.5 Mapping of Schedule 13G Submission Schemas to Submission Types

| Level | Order | Data Type | Element/Attribute Name                                  | Max Length | Choice List              | Max Occur | SCHEDULE 13G | SCHEDULE 13G/A |
| :---: | :---: | :-------- | :------------------------------------------------------ | ---------: | :----------------------- | :-------: | :----------: | :------------: |
|   1   |   1   | NV        | edgarSubmission                                         |            |                          |     1     |      m       |       m        |
|   2   |   1   | String    | schemaVersion                                           |          5 |                          |     1     |      o       |       o        |
|   2   |   2   | NV        | headerData                                              |            |                          |     1     |      m       |       m        |
|   3   |   1   | String    | submissionType                                          |            | SUBMISSION_TYPE          |     1     |      m       |       m        |
|   3   |   2   | String    | previousAccessionNumber                                 |         20 |                          |     1     |      NA      |       o        |
|   3   |   3   | NV        | filerInfo                                               |            |                          |     1     |      m       |       m        |
|   4   |   1   | NV        | filer                                                   |            |                          |     1     |      m       |       m        |
|   5   |   1   | NV        | filerCredentials                                        |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | cik                                                     |         10 |                          |     1     |      m       |       m        |
|   6   |   2   | String    | ccc                                                     |          8 |                          |     1     |      m       |       m        |
|   4   |   2   | String    | liveTestFlag                                            |            | LIVE_TEST_TYPE           |     1     |      m       |       m        |
|   4   |   3   | NV        | contact                                                 |            |                          |     1     |      m       |       m        |
|   5   |   1   | String    | contactName                                             |         30 |                          |     1     |      m       |       m        |
|   5   |   2   | String    | contactPhone                                            |         20 |                          |     1     |      m       |       m        |
|   5   |   3   | String    | contactEmail                                            |         80 |                          |     1     |      m       |       m        |
|   4   |   4   | NV        | flags                                                   |            |                          |     1     |      m       |       m        |
|   5   |   1   | Boolean   | overrideInternetFlag                                    |            | "true" or "false"        |     1     |      o       |       o        |
|   4   |   5   | NV        | notifications                                           |            |                          |     1     |      o       |       o        |
|   5   |   1   | String    | notificationEmail                                       |         80 |                          |     3     |      o       |       o        |
|   2   |   3   | NV        | formData                                                |            |                          |     1     |      m       |       m        |
|   3   |   1   | NV        | coverPageHeader                                         |            |                          |     1     |      m       |       m        |
|   4   |   1   | Number    | amendmentNo                                             |            |                          |     1     |      o       |       m        |
|   4   |   2   | String    | securitiesClassTitle                                    |            |                          |     1     |      m       |       m        |
|   4   |   3   | Date      | eventDateRequiresFilingThisStatement                    |            |                          |     1     |      m       |       m        |
|   4   |   4   | NV        | issuerInfo                                              |            |                          |     1     |      m       |       m        |
|   5   |   1   | String    | issuerCik                                               |         10 |                          |     1     |      m       |       m        |
|   5   |   2   | String    | issuerName                                              |        150 |                          |     1     |      m       |       m        |
|   5   |   3   | NV        | issuerCusips                                            |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | issuerCusipNumber                                       |         12 |                          |    20     |      m       |       m        |
|   5   |   4   | NV        | issuerPrincipalExecutiveOfficeAddress                   |            |                          |     1     |      m       |       m        |
|   6   |   1   | String    | street1                                                 |         40 |                          |     1     |      m       |       m        |
|   6   |   2   | String    | street2                                                 |         40 |                          |     1     |      o       |       o        |
|   6   |   3   | String    | city                                                    |         30 |                          |     1     |      m       |       m        |
|   6   |   4   | String    | stateOrCountry                                          |          2 |                          |     1     |      m       |       m        |
|   6   |   5   | String    | zipCode                                                 |         10 |                          |     1     |      m       |       m        |
|   4   |   5   | NV        | designateRulesPursuantThisScheduleFiled                 |            |                          |     1     |      o       |       o        |
|   5   |   1   | String    | designateRulePursuantThisScheduleFiled                  |          n | RULE_TYPE                |     3     |      o       |       o        |
|   3   |   2   | NV        | coverPageHeaderReportingPersonDetails                   |            |                          |    100    |      m       |       m        |
|   4   |   1   | String    | reportingCik                                            |         10 |                          |     1     |      o       |       o        |
|   4   |   2   | String    | reportingCikNotPresentInEdgarFlag                       |          1 | "Y" or "N'               |     1     |      o       |       o        |
|   4   |   3   | String    | reportingPersonName                                     |        150 |                          |     1     |      m       |       m        |
|   4   |   4   | String    | memberGroup                                             |          1 | GROUP_TYPE               |     1     |      o       |       o        |
|   4   |   5   | String    | citizenshipOrOrganization                               |          2 | STATE_COUNTRY_CODE       |     1     |      m       |       o        |
|   4   |   6   | NV        | reportingPersonBeneficiallyOwnedNumberOfShares          |         17 |                          |     1     |      m       |       o        |
|   5   |   1   | Number    | soleVotingPower                                         |         17 |                          |     1     |      m       |       o        |
|   5   |   2   | Number    | sharedVotingPower                                       |         17 |                          |     1     |      m       |       o        |
|   5   |   3   | Number    | soleDispositivePower                                    |         17 |                          |     1     |      m       |       o        |
|   5   |   4   | Number    | sharedDispositivePower                                  |         17 |                          |     1     |      m       |       o        |
|   4   |   7   | Number    | reportingPersonBeneficiallyOwnedAggregateNumberOfShares |         17 |                          |     1     |      m       |       o        |
|   4   |   8   | String    | aggregateAmountExcludesCertainSharesFlag                |          1 | "Y" or "N'               |     1     |      o       |       O        |
|   4   |   9   | Number    | classPercent                                            |          5 |                          |     1     |      m       |       o        |
|   4   |  10   | String    | typeOfReportingPerson                                   |          2 | TYPE_OF_REPORTING_PERSON |    14     |      m       |       o        |
|   4   |  11   | String    | comments                                                |      20000 |                          |     1     |      o       |       o        |
|   3   |   3   | NV        | items                                                   |            |                          |     1     |      m       |       o        |
|   4   |   1   | NV        | Item1                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | issuerName                                              |        150 |                          |     1     |      m       |       o        |
|   5   |   2   | String    | issuerPrincipalExecutiveOfficeAddress                   |        150 |                          |     1     |      m       |       o        |
|   4   |   2   | NV        | Item2                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | filingPersonName                                        |      20000 |                          |     1     |      m       |       o        |
|   5   |   2   | String    | principalBusinessOfficeOrResidenceAddress               |      20000 |                          |     1     |      m       |       o        |
|   5   |   3   | String    | citizenship                                             |       2000 |                          |     1     |      m       |       o        |
|   4   |   3   | NV        | Item3                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | typeOfPersonFiling                                      |          2 | BUSINESS_ENGAGED_TYPE    |    11     |      m       |       o        |
|   6   |   3   | String    | otherTypeOfPersonFiling                                 |      20000 |                          |     1     |      m#      |       m#       |
|   4   |   4   | NV        | Item4                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | amountBeneficiallyOwned                                 |      20000 |                          |     1     |      m       |       o        |
|   5   |   2   | Number    | classPercent                                            |          5 |                          |     1     |      m       |       o        |
|   5   |   3   | NV        | numberOfSharesPersonHas                                 |            |                          |     1     |      m       |       o        |
|   6   |   1   | String    | solePowerOrDirectToVote                                 |      20000 |                          |     1     |      m       |       o        |
|   6   |   2   | String    | sharedPowerOrDirectToVote                               |      20000 |                          |     1     |      m       |       o        |
|   6   |   3   | String    | solePowerOrDirectToDispose                              |      20000 |                          |     1     |      m       |       o        |
|   6   |   4   | String    | sharedPowerOrDirectToDispose                            |      20000 |                          |     1     |      m       |       o        |
|   4   |   5   | NV        | Item5                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | classOwnership5PercentOrLess                            |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   4   |   6   | NV        | Item6                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | ownershipMoreThan5PercentOnBehalfOfAnotherPerson        |      20000 |                          |     1     |      m       |       o        |
|   4   |   7   | NV        | Item7                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | subsidiaryIdentificationAndClassification               |      20000 |                          |     1     |      m       |       o        |
|   4   |   8   | NV        | Item8                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | identificationAndClassificationOfGroupMembers           |      20000 |                          |     1     |      m       |       o        |
|   4   |   9   | NV        | Item9                                                   |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | groupDissolutionNotice                                  |      20000 |                          |     1     |      m       |       o        |
|   4   |  10   | NV        | Item10                                                  |            |                          |     1     |      m       |       o        |
|   5   |   1   | String    | notApplicableFlag                                       |          1 | "Y" or "N'               |     1     |      m       |       o        |
|   5   |   2   | String    | certifications                                          |       2000 |                          |     1     |      m#      |       m#       |
|   3   |   4   | String    | exhibitInfo                                             |      20000 |                          |     1     |      o       |       o        |
|   3   |   5   | NV        | signatureInformation                                    |            |                          |    100    |      m       |       m        |
|   4   |   1   | String    | reportingPersonName                                     |        150 |                          |     1     |      m       |       m        |
|   4   |   2   | NV        | signatureDetails                                        |            |                          |    100    |      m       |       m        |
|   5   |   1   | String    | signature                                               |        150 |                          |     1     |      m       |       m        |
|   5   |   2   | String    | title                                                   |        150 |                          |     1     |      m       |       m        |
|   5   |   3   | Date      | date                                                    |            |                          |     1     |      m       |       m        |
|   3   |   6   | String    | signatureComments                                       |      20000 |                          |     1     |      o       |       o        |
|   2   |   4   | NV        | documents                                               |            |                          |     1     |      o       |       o        |
|   3   |   1   | NV        | document                                                |            |                          | unlimited |      o       |       o        |
|   4   |   1   | String    | conformedName                                           |         32 |                          |     1     |      o       |       o        |
|   4   |   2   | String    | conformedDocumentType                                   |            | SUB_DOCUMENT_TYPE        |     1     |      o       |       o        |
|   4   |   3   | String    | description                                             |        255 |                          |     1     |      o       |       o        |
|   4   |   4   | String    | contents                                                |            |                          |     1     |      o       |       o        |

<!-- SENTINEL: SCHEDULE_13D_CONSTRAINTS -->

## 4 SCHEDULE 13D SCHEMA DATA VALUE CONSTRAINTS

### 4.1 SUBMISSION_TYPE

These are the valid values for the `<submissionType>` element in the submission file:

| VALUE              | CODE DESCRIPTION                                                                                                                        |
| :----------------- | :-------------------------------------------------------------------------------------------------------------------------------------- |
| **SCHEDULE 13D**   | Schedule filed to report acquisition of beneficial ownership of more than 5% of certain classes of equity securities.                   |
| **SCHEDULE 13D/A** | An amendment to a schedule filed to report acquisition of beneficial ownership of more than 5% of certain classes of equity securities. |

### 4.2 LIVE_TEST_TYPE

These are the valid values for the `<liveTestFlag>` element in the submission file:

| VALUE  |
| :----- |
| `LIVE` |
| `TEST` |

### 4.3 MEMBER_TYPE

These are the valid values for the `<memberOfGroup>` element in the submission file:

| VALUE |
| :---: |
|  `a`  |
|  `b`  |

### 4.4 FUND_TYPE

These are the valid values for the `<fundType>` element in the submission file:

| VALUE  | Description                                                   |
| :----: | :------------------------------------------------------------ |
| **SC** | Subject Company - Company whose securities are being acquired |
| **BK** | Bank                                                          |
| **AF** | Affiliate - Affiliate of reporting person                     |
| **WC** | Working Capital - Working Capital of reporting person         |
| **PF** | Personal Funds - Personal Funds of reporting person           |
| **OO** | Other                                                         |

### 4.5 TYPE_OF_REPORTING_PERSON

These are the valid values for the `<typeOfReportingPerson>` element in the submission file:

| VALUE  | Description                             |
| :----: | :-------------------------------------- |
| **BD** | Broker Dealer                           |
| **BK** | Bank                                    |
| **CP** | Church Plan                             |
| **CO** | Corporation                             |
| **EP** | Employee Benefit Plan or Endowment Fund |
| **IN** | Individual                              |
| **IA** | Investment Adviser                      |
| **IC** | Insurance Company                       |
| **IV** | Investment Company                      |
| **HC** | Parent Holding Company/Control Person   |
| **PN** | Partnership                             |
| **SA** | Savings Association                     |
| **OO** | Other                                   |

<!-- SENTINEL: SCHEDULE_13G_CONSTRAINTS -->

## 5 SCHEDULE 13G SCHEMA DATA VALUE CONSTRAINTS

### 5.1 SUBMISSION_TYPE

These are the valid values for the `<submissionType>` element in the submission file:

| VALUE              | CODE DESCRIPTION                                                                                                                                                                  |
| :----------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **SCHEDULE 13G**   | Schedule filed to report beneficial ownership of more than 5% of certain classes of equity securities by passive, qualified institutional, or exempt investors.                   |
| **SCHEDULE 13G/A** | An amendment to a schedule filed to report beneficial ownership of more than 5% of certain classes of equity securities by passive, qualified institutional, or exempt investors. |

### 5.2 LIVE_TEST_TYPE

These are the valid values for the `<liveTestFlag>` element in the submission file:

| VALUE  |
| :----- |
| `LIVE` |
| `TEST` |

### 5.3 RULE_TYPE

These are the valid values for the `<memberGroup>` element in the submission file:

| VALUE           |
| :-------------- |
| `Rule 13d-1(b)` |
| `Rule 13d-1(c)` |
| `Rule 13d-1(d)` |

### 5.4 GROUP_TYPE

These are the valid values for the `<designateRulePursuantThisScheduleFiled>` element in the submission file:

| VALUE |
| :---: |
|  `a`  |
|  `b`  |

### 5.5 TYPE_OF_REPORTING_PERSON

These are the valid values for the `<typeOfReportingPerson>` element in the submission file:

| VALUE  | Description                             |
| :----: | :-------------------------------------- |
| **BD** | Broker Dealer                           |
| **BK** | Bank                                    |
| **CP** | Church Plan                             |
| **CO** | Corporation                             |
| **EP** | Employee Benefit Plan or Endowment Fund |
| **FI** | Non-U.S. Institution                    |
| **HC** | Parent Holding Company/Control Person   |
| **IA** | Investment Adviser                      |
| **IC** | Insurance Company                       |
| **IN** | Individual                              |
| **IV** | Investment Company                      |
| **PN** | Partnership                             |
| **SA** | Savings Associations                    |
| **OO** | Other                                   |

### 5.6 BUSINESS_ENGAGED_TYPE

These are the valid values for the `<typeOfPersonFiling>` element in the submission file:

| VALUE  | Description                                                                                                                                                                                 |
| :----: | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **BD** | Broker or dealer registered under section 15 of the Act (15 U.S.C. 78o);                                                                                                                    |
| **BK** | Bank as defined in section 3(a)(6) of the Act (15 U.S.C. 78c);                                                                                                                              |
| **CP** | A church plan that is excluded from the definition of an investment company under section 3(c)(14) of the Investment Company Act of 1940 (15 U.S.C. 80a-3);                                 |
| **EP** | An employee benefit plan or endowment fund in accordance with § 240.13d-1(b)(1)(ii)(F);                                                                                                     |
| **FI** | A non-U.S. institution in accordance with § 240.13d-1(b)(1)(ii)(J). If filing as a non-U.S. institution in accordance with § 240.13d-1(b)(1)(ii)(J), please specify the type of institution |
| **HC** | A parent holding company or control person in accordance with § 240.13d-1(b)(1)(ii)(G);                                                                                                     |
| **IA** | An investment adviser in accordance with § 240.13d-1(b)(1)(ii)(E);                                                                                                                          |
| **IC** | Insurance company as defined in section 3(a)(19) of the Act (15 U.S.C. 78c);                                                                                                                |
| **IV** | Investment company registered under section 8 of the Investment Company Act of 1940 (15 U.S.C. 80a-8);                                                                                      |
| **SA** | A savings associations as defined in Section 3(b) of the Federal Deposit Insurance Act (12 U.S.C. 1813);                                                                                    |
| **OO** | Group, in accordance with § 240.13d-1(b)(1)(ii)(K).                                                                                                                                         |

<!-- SENTINEL: BASIC_SUBMISSION_CONSTRUCTION -->

## 6 BASIC SUBMISSION CONSTRUCTION

### 6.1 General Formatting of XML Files

The following rules apply to the submission file of an XML-format Schedule 13D and Schedule 13G submissions:

1. The filename must end with an `.xml` extension.
2. The file cannot be compressed in any fashion.
3. We strongly recommend you format with indentation the submission as shown in the provided sample files. This makes the raw XML files easier to view in a text editor. The submission of ASCII XML files with no line breaks, while legal XML is strongly discouraged. XML filings are required to be posted on public websites. While usually formatted via style sheets, the raw XML is frequently available for inspection and should be readable by a person. A single line XML file is not viewer-friendly and should be avoided.
4. The `<?xml version="1.0"?>` declaration line is optional; however, if it is included it must be the first line in the file. Any text entered before this line, even white space, will cause a **SUSPENSE** error. The version value must be `"1.0"`. Any other value for version will cause a **SUSPENSE** error.
5. For an XML element with a data value, keep the begin tag, data value, and end tag on the same line of text. Otherwise, you could get a schema violation error. As an example, for a filer ID value which cannot be longer than 10 characters, this specification is correct:

```xml
<cik>1212121212</cik>
```

6. The specification below will result in a parsing error because the extraneous white space and line feeds will be counted as part of the length of the data value. In other words, the CIK value will be regarded as longer than 10 characters:

```xml
<cik>
1212121212
</cik>
```

### 6.2 XML Submission File Rules

The following rules apply to the supporting document XML-format:

1. The `<?xml version="1.0"?>` declaration line is optional; however, if it is included it must be the first line in the file. Any text entered before this line, even white space, will cause a **SUSPENSE** error.
