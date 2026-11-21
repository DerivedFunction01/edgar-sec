"""Section taxonomy for Form 40-APP exemptive applications under the
Investment Company Act of 1940: the sections filed specimens evidence,
in filed order. Headings are filed bare or roman-numbered; the numbered
name variants are the pairings the specimen draw evidences.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_40APP_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "INTRODUCTION",
        1,
        (
            "introduction",
            "i. introduction",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "SUMMARY OF APPLICATION",
        1,
        (
            "summary of application",
            "i. summary of application",
        ),
        optional=True,
    ),
    ItemDefinition(
        "APPLICANTS",
        1,
        (
            "applicants",
            "i. applicants",
            "ii. applicants",
            "general description of the applicants",
            "ii. general description of the applicants",
            "i. general description of applicants",
            "description of applicants",
        ),
        optional=True,
    ),
    ItemDefinition(
        "BACKGROUND",
        1,
        (
            "background",
            "i. background",
            "ii. background",
        ),
        optional=True,
    ),
    ItemDefinition(
        "REQUEST FOR ORDER",
        1,
        (
            "request for order",
            "order requested",
            "request for order of exemption",
            "relief requested",
            "iii. request for order",
            "iv. request for order",
            "iii. order requested",
            "ii. relief requested",
            "i. requested relief",
            "iii. request for exemptive relief",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT IN SUPPORT OF RELIEF REQUESTED",
        1,
        (
            "statement in support of relief requested",
            "statement in support of the requested order",
            "statement in support of the application",
            "in support of the application",
            "legal analysis",
            "iii. statement in support of relief requested",
            "iv. statement in support of relief requested",
            "v. statement in support of the requested order",
            "iv. in support of the application",
            "ii. legal analysis",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PRECEDENTS",
        1,
        (
            "precedents",
            "precedent",
            "v. precedents",
            "iii. precedent",
            "ix. precedent",
        ),
        optional=True,
    ),
    ItemDefinition(
        "CONDITIONS",
        1,
        (
            "conditions",
            "applicants' conditions",
            "applicants’ conditions",
            "iv. conditions",
            "v. conditions",
            "iv. applicants' conditions",
            "vii. applicants' conditions",
            "x. applicants' conditions",
        ),
        optional=True,
    ),
    ItemDefinition(
        "CONCLUSION",
        1,
        (
            "conclusion",
            "v. conclusion",
            "vi. conclusion",
            "vii. conclusion",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PROCEDURAL MATTERS",
        1,
        (
            "procedural matters",
            "iii. procedural matters",
            "v. procedural matters",
            "vi. procedural matters",
            "vii. procedural matters",
            "viii. procedural matters",
            "vii. procedural matters, conclusions and signatures",
        ),
        optional=True,
    ),
    ItemDefinition(
        "VERIFICATION",
        1,
        ("verification",),
        optional=True,
    ),
    ItemDefinition(
        "SIGNATURES",
        1,
        (
            "signatures",
            "signature",
            "authorization and signatures",
            "viii. authorization and signatures",
            "x. authorization and signatures",
        ),
        optional=True,
    ),
    ItemDefinition(
        "EXHIBIT INDEX",
        1,
        (
            "exhibit index",
            "index to exhibits",
            "exhibits",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_40APP_ITEMS"]
