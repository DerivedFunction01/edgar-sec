"""Item taxonomy for current reports (8-K, 6-K)."""

from __future__ import annotations

ITEMS: dict[str, str] = {
    "ITEM 1.01": "Entry into a Material Definitive Agreement",
    "ITEM 1.02": "Termination of a Material Definitive Agreement",
    "ITEM 2.01": "Completion of Acquisition or Disposition of Assets",
    "ITEM 2.02": "Results of Operations and Financial Condition",
    "ITEM 5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers",
    "ITEM 7.01": "Regulation FD Disclosure",
    "ITEM 8.01": "Other Events",
    "ITEM 9.01": "Financial Statements and Exhibits",
}

__all__ = ["ITEMS"]
