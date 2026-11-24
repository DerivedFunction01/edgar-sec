"""Statement-view driver vocabulary: surfaces, labels, mechanisms."""

from __future__ import annotations


TOLERANCE = 0.5


STATEMENT_FACTORIES = (
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comprehensive_income_statement",
    "plan_net_assets",
    "plan_changes",
    "fund_assets_liabilities",
    "fund_operations",
)


SCALARS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "operating_cash_flow",
    "rpo",
    "capex",
    "free_cash_flow",
    "uncommenced_leases",
)


SERIES = (
    "revenue_series",
    "gross_profit_series",
    "operating_income_series",
    "net_income_series",
    "total_assets_series",
    "total_liabilities_series",
    "total_equity_series",
    "operating_cash_flow_series",
    "rpo_series",
    "capex_series",
)


YOY = (
    "revenue_yoy",
    "gross_profit_yoy",
    "operating_income_yoy",
    "net_income_yoy",
    "total_assets_yoy",
    "total_liabilities_yoy",
    "total_equity_yoy",
    "operating_cash_flow_yoy",
    "rpo_yoy",
)


TOPIC_VIEWS = (
    "derivatives",
    "debt",
    "cash_rollforward",
    "fair_value_hierarchy",
)


FINANCIAL_VIEWS = TOPIC_VIEWS + (
    "level3_rollforward",
    "pension_funded_status",
    "segment_breakdown",
)


FAITHFUL = "served-faithful"


HONEST = "served-honest"


BLOCKED = "blocked"


MECH_ROOT = "missing root atom"


MECH_LABEL = "taxonomy-shaped label gap"


MECH_FISCAL = "fiscal-class refusal"


MECH_ACQUISITION = "acquisition posture"


MECH_PARSE = "parse posture"


MECH_UNVERIFIED = "served value not in filed facts"


MECH_EXCEPTION = "surface exception"


MECH_FACE = "face total absent from statement face"


MECH_MODE = "mode-order violation"
