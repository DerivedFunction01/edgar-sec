"""Canonical Item and Part taxonomy definitions for SEC Forms (10-K, 10-Q, 8-K)."""

from __future__ import annotations

# Standard Form 10-K Parts and Items
FORM_10K_PARTS = ("PART I", "PART II", "PART III", "PART IV")

FORM_10K_ITEMS = {
    "ITEM 1": "Business",
    "ITEM 1A": "Risk Factors",
    "ITEM 1B": "Unresolved Staff Comments",
    "ITEM 1C": "Cybersecurity",
    "ITEM 2": "Properties",
    "ITEM 3": "Legal Proceedings",
    "ITEM 4": "Mine Safety Disclosures",
    "ITEM 5": "Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities",
    "ITEM 6": "Selected Financial Data",
    "ITEM 7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "ITEM 7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "ITEM 8": "Financial Statements and Supplementary Data",
    "ITEM 9": "Changes in and Disagreements With Accountants on Accounting and Financial Disclosure",
    "ITEM 9A": "Controls and Procedures",
    "ITEM 9B": "Other Information",
    "ITEM 9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "ITEM 10": "Directors, Executive Officers and Corporate Governance",
    "ITEM 11": "Executive Compensation",
    "ITEM 12": "Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters",
    "ITEM 13": "Certain Relationships and Related Transactions, and Director Independence",
    "ITEM 14": "Principal Accountant Fees and Services",
    "ITEM 15": "Exhibit and Financial Statement Schedules",
    "ITEM 16": "Form 10-K Summary",
}

# Standard Form 10-Q Parts and Items
FORM_10Q_PARTS = ("PART I", "PART II")

FORM_10Q_ITEMS = {
    "ITEM 1": "Financial Statements",
    "ITEM 2": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "ITEM 3": "Quantitative and Qualitative Disclosures About Market Risk",
    "ITEM 4": "Controls and Procedures",
    "ITEM 1A": "Risk Factors",
    "ITEM 5": "Other Information",
    "ITEM 6": "Exhibits",
}

# Standard Form 8-K Items
FORM_8K_ITEMS = {
    "ITEM 1.01": "Entry into a Material Definitive Agreement",
    "ITEM 1.02": "Termination of a Material Definitive Agreement",
    "ITEM 2.01": "Completion of Acquisition or Disposition of Assets",
    "ITEM 2.02": "Results of Operations and Financial Condition",
    "ITEM 5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers",
    "ITEM 7.01": "Regulation FD Disclosure",
    "ITEM 8.01": "Other Events",
    "ITEM 9.01": "Financial Statements and Exhibits",
}

__all__ = [
    "FORM_8K_ITEMS",
    "FORM_10K_ITEMS",
    "FORM_10K_PARTS",
    "FORM_10Q_ITEMS",
    "FORM_10Q_PARTS",
]
