"""Compositional concept decomposer extracting semantic frames and sub-atomic modifiers."""

from __future__ import annotations

from edgar_sec.engine.xbrl.domain import DomainTaxonomy, SemanticConceptFrame


def split_camel_case(name: str) -> tuple[str, ...]:
    """Split CamelCase identifier into individual word tokens."""
    cleaned = name.replace("_", " ")
    tokens: list[str] = []
    current: list[str] = []
    for i, ch in enumerate(cleaned):
        if ch.isupper() and current:
            prev = cleaned[i - 1]
            next_ch = cleaned[i + 1] if i + 1 < len(cleaned) else ""
            if prev.islower() or (next_ch and next_ch.islower()):
                tokens.append("".join(current))
                current = []
        elif ch.isdigit() and current and not cleaned[i - 1].isdigit():
            tokens.append("".join(current))
            current = []
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tuple(t for t in tokens if t)


def infer_semantic_frame(
    concept_qname: str,
    taxonomy: DomainTaxonomy,
    *,
    unit: str | None = None,
    balance: str | None = None,
    role_uri: str | None = None,
) -> SemanticConceptFrame:
    """Decompose an XBRL concept into a 7-slot structured semantic frame."""
    local_name = concept_qname.split(":")[-1] if ":" in concept_qname else concept_qname
    tokens = split_camel_case(local_name)
    tok_set = set(tokens)
    joined = "".join(tokens)

    # 1. Match sub-atomic modifiers from taxonomy pattern keywords
    matched_mods: list[str] = []
    for mod in taxonomy.subatomic_modifiers:
        if any(kw in joined or kw in tok_set for kw in mod.keywords if kw):
            matched_mods.append(mod.modifier_id)

    # 2. Determine indivisible prime head
    head = "H_ASSET"
    unit_str = (unit or "").lower()
    bal_str = (balance or "").upper()

    if unit_str in ("shares", "shares_k", "shares_m") or "Shares" in tok_set:
        head = "H_SHARE_UNIT"
    elif unit_str in ("pure", "ratio", "percent", "count") or any(
        t in tok_set
        for t in ("Percentage", "Percent", "Ratio", "Employees", "Headcount")
    ):
        head = "H_METRIC_RATIO"
    elif "RemainingPerformanceObligation" in joined or "Commitment" in joined:
        head = "H_COMMITMENT"
    elif "AccumulatedOtherComprehensive" in joined or "AOCI" in joined:
        head = "H_AOCI_STOCK"
    elif "OtherComprehensiveIncome" in joined:
        head = "H_OCI_FLOW"
    elif any(t in tok_set for t in ("Gain", "Gains", "Loss", "Losses")) and not any(
        t in joined for t in ("OperatingIncomeLoss", "NetIncomeLoss", "ProfitLoss")
    ):
        head = "H_GAIN_LOSS"
    elif any(
        t in joined
        for t in (
            "CashAndCashEquivalents",
            "RestrictedCash",
            "CashProvidedByUsedIn",
        )
    ):
        head = "H_CASH"
    elif (
        any(t in joined for t in ("Revenue", "Revenues", "PremiumsEarned"))
        and "Unearned" not in joined
        and "DeferredRevenue" not in joined
    ):
        head = "H_REVENUE"
    elif any(
        t in joined
        for t in ("CostOfGoods", "CostOfSales", "CostOfRevenue", "Consumables")
    ):
        head = "H_COST"
    elif any(
        t in joined
        for t in (
            "GrossProfit",
            "OperatingIncomeLoss",
            "NetIncomeLoss",
            "ProfitLoss",
        )
    ):
        head = "H_NET_INCOME"
    elif any(
        t in tok_set
        for t in (
            "Expense",
            "Expenses",
            "Tax",
            "Taxes",
            "Depreciation",
            "Amortization",
        )
    ):
        head = "H_EXPENSE"
    elif any(
        t in joined
        for t in (
            "TreasuryStock",
            "AccumulatedDepreciation",
            "AccumulatedAmortization",
            "AllowanceFor",
        )
    ):
        head = "H_CONTRA"
    elif any(
        t in joined for t in ("StockholdersEquity", "CommonStock", "RetainedEarnings")
    ):
        head = "H_EQUITY"
    elif (
        any(
            t in joined
            for t in (
                "Liabilities",
                "Liability",
                "Payable",
                "UnearnedRevenue",
                "Debt",
            )
        )
        or bal_str == "CREDIT"
    ):
        head = "H_LIABILITY"

    # 3. Recognition book
    if head == "H_OCI_FLOW":
        book = "B_OCI_UNREALIZED"
    elif head == "H_AOCI_STOCK":
        book = "B_EQUITY_AOCI_RESERVE"
    elif head in ("H_ASSET", "H_LIABILITY", "H_EQUITY", "H_CONTRA"):
        book = "B_BALANCE_SHEET"
    elif head == "H_CASH":
        book = "B_CASH_FLOW_STATEMENT"
    else:
        book = "B_INCOME_STATEMENT"

    # 4. Flow vs Stock and Realization
    flow_stock = (
        "STOCK"
        if head in ("H_ASSET", "H_LIABILITY", "H_EQUITY", "H_AOCI_STOCK")
        else "FLOW"
    )
    horizon = "POINT_IN_TIME" if flow_stock == "STOCK" else "DURATION_PERIOD"
    valuation = (
        "FAIR_VALUE" if "M_UNREALIZED" in matched_mods else "HISTORICAL_AMORTIZED_COST"
    )
    realization = "UNREALIZED_M2M" if "M_UNREALIZED" in matched_mods else "REALIZED_P_L"

    return SemanticConceptFrame(
        qname=concept_qname,
        prime_head=head,
        modifiers=tuple(matched_mods),
        recognition_book=book,
        flow_stock=flow_stock,
        timing_horizon=horizon,
        valuation_basis=valuation,
        realization_state=realization,
    )
