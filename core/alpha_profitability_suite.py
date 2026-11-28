#!/usr/bin/env python3
"""
8888 — Aegis V10 Profitability & Microstructure Unified Orchestrator (`core/alpha_profitability_suite.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Executes Phase 1 (M36~M38), Phase 2 (M39, M40, M43), and Phase 3 (M41, M42, M44) safely with
per-module exception isolation, persists `data/alpha_profitability_report.json`, and returns
unified alerts and per-bot scorecards for Level 2+ autonomous remediation.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.profitability_phase1_auditor import (
    _atomic_write_json,
    _load_json,
    audit_cusum_sprt_edge_decay,
    audit_mae_mfe_exit_efficiency,
    audit_slippage_and_spread_atr,
)
from core.profitability_phase2_auditor import (
    audit_directional_expectancy_skew,
    audit_funding_carry_and_settlement_whipsaw,
    audit_intraday_weekend_seasonality,
)
from core.profitability_phase3_auditor import (
    audit_live_correlation_and_hrp_budget,
    audit_oi_basis_crowding,
    audit_shadow_signals_and_post_exit_drift,
)
from watchdog_common import BASE_8888

ALPHA_REPORT_FILE = os.path.join(BASE_8888, "data", "alpha_profitability_report.json")


def run_alpha_profitability_suite(
    bots: List[Any],
    baselines_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run M36~M44 profitability diagnostics cleanly and persist report JSON."""
    t0 = time.time()
    bot_strs = [str(b) for b in bots]
    if baselines_doc is None:
        baselines_doc = _load_json(os.path.join(BASE_8888, "strategy_baselines.json"), {}) or {}

    errors: Dict[str, str] = {}
    alerts: List[Dict[str, Any]] = []

    def _safe_call(name: str, fn, *args, **kwargs) -> Dict[str, Any]:
        try:
            res = fn(*args, **kwargs) or {}
            alerts.extend(res.get("alerts") or [])
            return res
        except Exception as exc:
            errors[name] = str(exc)
            return {"per_bot": {}, "alerts": [], "error": str(exc)}

    m36 = _safe_call("M36", audit_mae_mfe_exit_efficiency, bot_strs)
    m37 = _safe_call("M37", audit_slippage_and_spread_atr, bot_strs)
    m38 = _safe_call("M38", audit_cusum_sprt_edge_decay, bot_strs, baselines_doc)

    m39 = _safe_call("M39", audit_funding_carry_and_settlement_whipsaw, bot_strs)
    m40 = _safe_call("M40", audit_intraday_weekend_seasonality, bot_strs)
    m43 = _safe_call("M43", audit_directional_expectancy_skew, bot_strs)

    m41 = _safe_call("M41", audit_oi_basis_crowding, bot_strs)
    m42 = _safe_call("M42", audit_live_correlation_and_hrp_budget, bot_strs)
    m44 = _safe_call("M44", audit_shadow_signals_and_post_exit_drift, bot_strs)

    per_bot_summary: Dict[str, Dict[str, Any]] = {}
    hrp_weights = m42.get("hrp_weights") or {}
    rec_risk = m42.get("recommended_risk_pct") or {}

    for bid in bot_strs:
        per_bot_summary[bid] = {
            "m36": (m36.get("per_bot") or {}).get(bid, {}),
            "m37": (m37.get("per_bot") or {}).get(bid, {}),
            "m38": (m38.get("per_bot") or {}).get(bid, {}),
            "m39": (m39.get("per_bot") or {}).get(bid, {}),
            "m40": (m40.get("per_bot") or {}).get(bid, {}),
            "m41": (m41.get("per_bot") or {}).get(bid, {}),
            "m42": {
                "hrp_weight": hrp_weights.get(bid),
                "recommended_risk_pct": rec_risk.get(bid),
            },
            "m43": (m43.get("per_bot") or {}).get(bid, {}),
            "m44": (m44.get("per_bot") or {}).get(bid, {}),
        }

    elapsed = round(time.time() - t0, 2)
    report = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "modules": ["M36", "M37", "M38", "M39", "M40", "M41", "M42", "M43", "M44"],
        "errors": errors,
        "m36_mae_mfe": m36,
        "m37_slippage_spread": m37,
        "m38_cusum_sprt": m38,
        "m39_funding_carry": m39,
        "m40_seasonality": m40,
        "m41_oi_crowding": m41,
        "m42_corr_hrp": m42,
        "m43_dir_skew": m43,
        "m44_shadow_drift": m44,
        "per_bot_summary": per_bot_summary,
        "alerts": alerts,
    }
    _atomic_write_json(ALPHA_REPORT_FILE, report)
    return report
