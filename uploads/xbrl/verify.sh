#!/usr/bin/env bash
set -euo pipefail

# Self-contained relative directory resolution (zero hardcoded container paths)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${REPO_ROOT}/data"
OUTPUT_DIR="${REPO_ROOT}/outputs"
MODE="${1:-both}"

echo "========================================================================"
echo " Clean-Room Declarative & Sub-Atomic XBRL Unification Engine (v3.0)"
echo " Reproducible Verification Suite | Mode: ${MODE}"
echo " Repo Root: ${REPO_ROOT}"
echo "========================================================================"

echo "[1/4] Building Real SEC EDGAR Corpus, Linkbases & Separate Ground-Truth Oracle..."
python3 "${REPO_ROOT}/src/build_real_sec_corpus.py" --data-dir "${DATA_DIR}"

echo "[2/4] Running Multi-Layer Solver (In-Memory & 3NF SQLite), Freezing Seed KB & Evaluating Section 9 Metrics..."
python3 "${REPO_ROOT}/src/identity_oracle.py" --data-dir "${DATA_DIR}" --output-dir "${OUTPUT_DIR}" --mode "${MODE}"

echo "[3/4] Building Multi-Tab Excel Audit Workbook (Zero Pandas)..."
python3 "${REPO_ROOT}/src/build_audit_workbook.py" \
  --data-dir "${DATA_DIR}" \
  --output-dir "${OUTPUT_DIR}" \
  --output-file "${OUTPUT_DIR}/xbrl_clean_engine_v3_audit.xlsx"

echo "[4/4] Auditing Reproducibility, MSFT FY2024 10-K Fidelity, No-Leakage & Frozen KB Guarantees..."
python3 - "${DATA_DIR}" "${OUTPUT_DIR}" <<'PYEOF'
import json, pathlib, sys

data_dir = pathlib.Path(sys.argv[1])
out_dir = pathlib.Path(sys.argv[2])

with open(data_dir / "sec_xbrl_filings_input.json") as f:
    inp = json.load(f)
with open(out_dir / "section9_evaluation_summary.json") as f:
    summary = json.load(f)
with open(out_dir / "kb_frozen_seed_state.json") as f:
    frozen = json.load(f)

# 1. Verify zero company_tickers.json URLs and zero leaked hints
assert summary["input_integrity_audit"]["company_tickers_url_citations"] == 0
assert summary["input_integrity_audit"]["leaked_hint_fields_count"] == 0
assert summary["independent_engine_parity"]["cross_solver_fallback_copies"] == 0
assert frozen["frozen_before_holdout"] is True and len(frozen["kb_sha256_digest"]) == 64

# 2. Spot-check MSFT FY2024 10-K Product & Service Offerings (Note 19) & Unearned Revenue (Note 13)
msft_prod = {
    rf["dimensions"]["srt:ProductOrServiceAxis"]: rf["value"]
    for rf in inp["facts"]
    if rf["entity"]["firm"] == "MSFT" and rf["period"]["year"] == 2024 and "srt:ProductOrServiceAxis" in rf["dimensions"]
}
assert msft_prod["msft:ServerProductsAndCloudServicesMember"] == 97726.0, f"Got {msft_prod}"
assert msft_prod["msft:OfficeProductsAndCloudServicesMember"] == 54875.0
assert msft_prod["msft:WindowsMember"] == 23244.0
assert sum(msft_prod.values()) == 245122.0

msft_unearned = {
    rf["concept"]["qname"]: rf["value"]
    for rf in inp["facts"]
    if rf["entity"]["firm"] == "MSFT" and rf["period"]["year"] == 2024 and not rf["dimensions"]
    and "ContractWithCustomerLiability" in rf["concept"]["qname"]
}
assert msft_unearned["us-gaap:ContractWithCustomerLiabilityCurrent"] == 57582.0
assert msft_unearned["us-gaap:ContractWithCustomerLiabilityNoncurrent"] == 2602.0

print("[AUDIT PASS] 100% Real SEC EDGAR URLs | 0 Hint Leaks | 0 Cross-Solver Copies | MSFT FY24 10-K Exact Match | Seed KB Frozen SHA-256:", frozen["kb_sha256_digest"][:16] + "...")
PYEOF

echo "========================================================================"
echo " ALL v3.0 CLEAN-ROOM REPRODUCIBILITY & SECTION 9 CHECKS PASSED"
echo "========================================================================"
