"""Constitutive label sequences: measured values with calibration provenance."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.registry import (
    PROV_COVERAGE_DISCOVERY,
    PROV_SEQUENCES,
)


@dataclass(frozen=True, slots=True)
class SequenceSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    terms: tuple[str, ...]
    support: int
    provenance: str = PROV_SEQUENCES


SEQUENCES: tuple[SequenceSpec, ...] = (
    SequenceSpec(
        "income_statement", ("operating expenses", "total operating expenses"), 46
    ),
    SequenceSpec(
        "income_statement", ("operating expenses", "general and administrative"), 35
    ),
    SequenceSpec(
        "income_statement",
        ("general and administrative", "total operating expenses"),
        33,
    ),
    SequenceSpec(
        "income_statement", ("research and development", "total operating expenses"), 31
    ),
    SequenceSpec(
        "income_statement", ("operating expenses", "research and development"), 30
    ),
    SequenceSpec("income_statement", ("research and development", "net loss"), 27),
    SequenceSpec("income_statement", ("operating expenses", "net loss"), 26),
    SequenceSpec("income_statement", ("total operating expenses", "net loss"), 26),
    SequenceSpec(
        "income_statement",
        ("research and development", "general and administrative"),
        26,
    ),
    SequenceSpec("income_statement", ("gross profit", "research and development"), 25),
    SequenceSpec("income_statement", ("general and administrative", "net loss"), 25),
    SequenceSpec("income_statement", ("loss from operations", "net loss"), 24),
    SequenceSpec("income_statement", ("gross profit", "operating expenses"), 23),
    SequenceSpec("income_statement", ("gross profit", "interest expense"), 22),
    SequenceSpec(
        "income_statement", ("operating expenses", "loss from operations"), 22
    ),
    SequenceSpec(
        "income_statement",
        (
            "operating expenses",
            "general and administrative",
            "total operating expenses",
        ),
        31,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "research and development", "total operating expenses"),
        25,
    ),
    SequenceSpec(
        "income_statement",
        (
            "operating expenses",
            "research and development",
            "general and administrative",
        ),
        21,
    ),
    SequenceSpec(
        "income_statement",
        (
            "research and development",
            "general and administrative",
            "total operating expenses",
        ),
        20,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "total operating expenses", "net loss"),
        19,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "general and administrative", "net loss"),
        18,
    ),
    SequenceSpec(
        "income_statement",
        ("research and development", "general and administrative", "net loss"),
        18,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "general and administrative", "loss from operations"),
        17,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "loss from operations", "net loss"),
        17,
    ),
    SequenceSpec(
        "income_statement",
        ("general and administrative", "total operating expenses", "net loss"),
        17,
    ),
    SequenceSpec("balance_sheet", ("total assets", "total liabilities"), 91),
    SequenceSpec("balance_sheet", ("assets", "total assets"), 90),
    SequenceSpec("balance_sheet", ("assets", "total liabilities"), 80),
    SequenceSpec("balance_sheet", ("total current assets", "total assets"), 68),
    SequenceSpec("balance_sheet", ("current assets", "total assets"), 67),
    SequenceSpec("balance_sheet", ("assets", "total current assets"), 65),
    SequenceSpec("balance_sheet", ("total assets", "current liabilities"), 64),
    SequenceSpec("balance_sheet", ("assets", "current assets"), 63),
    SequenceSpec("balance_sheet", ("cash and cash equivalents", "total assets"), 63),
    SequenceSpec(
        "balance_sheet", ("total current assets", "total current liabilities"), 63
    ),
    SequenceSpec("balance_sheet", ("current assets", "current liabilities"), 63),
    SequenceSpec("balance_sheet", ("total assets", "total current liabilities"), 62),
    SequenceSpec("balance_sheet", ("current assets", "total current assets"), 61),
    SequenceSpec("balance_sheet", ("assets", "current liabilities"), 60),
    SequenceSpec("balance_sheet", ("assets", "cash and cash equivalents"), 59),
    SequenceSpec("balance_sheet", ("assets", "total assets", "total liabilities"), 80),
    SequenceSpec(
        "balance_sheet", ("assets", "total current assets", "total assets"), 64
    ),
    SequenceSpec("balance_sheet", ("assets", "current assets", "total assets"), 62),
    SequenceSpec(
        "balance_sheet",
        ("total current assets", "total assets", "total current liabilities"),
        62,
    ),
    SequenceSpec(
        "balance_sheet", ("current assets", "total assets", "current liabilities"), 62
    ),
    SequenceSpec(
        "balance_sheet", ("current assets", "total current assets", "total assets"), 61
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "current assets", "total current assets"), 60
    ),
    SequenceSpec(
        "balance_sheet",
        ("assets", "total current assets", "total current liabilities"),
        59,
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "current assets", "current liabilities"), 59
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "total assets", "current liabilities"), 59
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        64,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from financing activities",
        ),
        63,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
        ),
        61,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        39,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "net cash used in investing activities",
        ),
        38,
    ),
    SequenceSpec("cash_flow", ("operating activities", "investing activities"), 36),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from financing activities",
        ),
        36,
    ),
    SequenceSpec("cash_flow", ("investing activities", "financing activities"), 35),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "changes in operating assets and liabilities",
        ),
        35,
    ),
    SequenceSpec("cash_flow", ("operating activities", "financing activities"), 34),
    SequenceSpec(
        "cash_flow",
        ("depreciation and amortization", "cash flows from investing activities"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        ("depreciation and amortization", "cash flows from financing activities"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from investing activities",
        ),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        ("cash flows from operating activities", "depreciation and amortization"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "net cash used in investing activities",
            "net cash provided by financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        56,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        37,
    ),
    SequenceSpec(
        "cash_flow",
        ("operating activities", "investing activities", "financing activities"),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "depreciation and amortization",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "changes in operating assets and liabilities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "depreciation and amortization",
            "cash flows from investing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "depreciation and amortization",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
            "net cash used in investing activities",
        ),
        32,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        32,
    ),
    SequenceSpec(
        "stock_comp_rollforward",
        ("granted", "exercised"),
        6,
        PROV_COVERAGE_DISCOVERY,
    ),
    SequenceSpec(
        "aoci_rollforward",
        ("balance at beginning of period", "balance at end of period"),
        3,
        PROV_COVERAGE_DISCOVERY,
    ),
    SequenceSpec(
        "aoci_rollforward",
        ("beginning balance", "ending balance"),
        3,
        PROV_COVERAGE_DISCOVERY,
    ),
)
