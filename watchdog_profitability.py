#!/usr/bin/env python3
"""
8888 — Proactive Strategy Lifecycle & Threshold Monitor (watchdog_profitability.py)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
역할:
  1. strategy_baselines.json에 등록된 3~5년 실측 백테스트 기대치(MDD, 최대연패, 수수료 비중,
     최소 관측 표본일)와 실제 거래소/장부 데이터(snapshots.json, peak_assets.json, stats.json,
     trade_history.csv, config.json)를 5분 주기로 대조 감시한다.
  2. 임계치 초과, 수수료 잠식, 생존 설정 미비, 표본 검증 시점 도달 시 임의로 봇 코드나
     config.json을 수정하거나 강제 재기동하지 않고, data/lifecycle_status.json 기록 +
     data/proactive_alerts.json 등록 + Discord 사전 승인 제안 알림만 발송한다.

[보스 특별 규칙 준수]
  - 개별 봇 폴더(8401~8408)의 *.py, config.json, Lock 파일은 절대 쓰기/삭제 금지 (Read-Only).
  - 8401, 8402, 8403, 8405: 5단계 명시적 승인(5-Step Approval) 대상
  - 8404, 8408: 2단계 명시적 승인(2-Step Approval) 대상
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import csv
import fcntl
import json
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta

BASE_8888 = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_8888)
if BASE_8888 not in sys.path:
    sys.path.insert(0, BASE_8888)

from watchdog_common import (  # noqa: E402
    clear_proactive_alert,
    load_proactive_alerts,
    record_proactive_alert,
    setup_clean_logger,
)

ACTIVE_BOTS = ["8401", "8402", "8403", "8404", "8405", "8408"]
CHECK_INTERVAL_SEC = 300
LOCK_PATH = "/tmp/watchdog_profitability.lock"
LOG_PATH = os.path.join(BASE_8888, "watchdog_profitability.log")
BASELINES_PATH = os.path.join(BASE_8888, "strategy_baselines.json")
LIVE_BALANCES_PATH = os.path.join(BASE_8888, "data", "live_balances.json")
PEAK_ASSETS_PATH = os.path.join(BASE_8888, "peak_assets.json")
SNAPSHOTS_PATH = os.path.join(BASE_8888, "snapshots.json")
LIFECYCLE_STATUS_PATH = os.path.join(BASE_8888, "data", "lifecycle_status.json")

_log = setup_clean_logger(LOG_PATH)


def _atomic_save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=os.path.basename(path) + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default


def _parse_dt(val):
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(val[:19], fmt)
        except ValueError:
            continue
    return None


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _analyze_trade_history(csv_path, perf_start_dt, now_dt):
    """
    trade_history.csv를 읽어 perf_start_time 이후 누적 및 최근 7일 수수료·손익·연패를 집계한다.
    동일 주문ID의 분할 체결 청산은 1건의 청산 거래로 병합하여 연패 수 왜곡을 방지한다.
    """
    result = {
        "closed_trades_all": 0,
        "wins_all": 0,
        "losses_all": 0,
        "gross_pnl_all": 0.0,
        "fees_all": 0.0,
        "net_pnl_all": 0.0,
        "fee_ratio_all_pct": None,
        "fee_deficit_all": False,
        "closed_trades_7d": 0,
        "gross_pnl_7d": 0.0,
        "fees_7d": 0.0,
        "net_pnl_7d": 0.0,
        "fee_ratio_7d_pct": None,
        "fee_deficit_7d": False,
        "cur_loss_streak": 0,
        "max_loss_streak": 0,
        "first_trade_ts": None,
        "last_trade_ts": None,
    }
    if not os.path.exists(csv_path):
        return result

    cutoff_7d = now_dt - timedelta(days=7)
    grouped_closes = {}
    close_order = []
    anon_seq = 0

    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = (row.get("시간") or row.get("time") or "").strip()
                ts_dt = _parse_dt(ts_str)
                if ts_dt is None:
                    continue
                if perf_start_dt and ts_dt < perf_start_dt:
                    continue

                if result["first_trade_ts"] is None or ts_str < result["first_trade_ts"]:
                    result["first_trade_ts"] = ts_str
                if result["last_trade_ts"] is None or ts_str > result["last_trade_ts"]:
                    result["last_trade_ts"] = ts_str

                fee = abs(_safe_float(row.get("수수료(USDT)") or row.get("fee"), 0.0))
                result["fees_all"] += fee
                if ts_dt >= cutoff_7d:
                    result["fees_7d"] += fee

                row_type = (row.get("유형") or row.get("type") or "").strip()
                is_close = ("청산" in row_type) or (row_type.lower() == "close")
                if not is_close:
                    continue

                pnl = _safe_float(row.get("수익(USDT)") or row.get("pnl"), 0.0)
                sym = (row.get("심볼") or row.get("symbol") or "").strip()
                ord_id = (row.get("주문ID") or row.get("order_id") or "").strip()
                if ord_id and ord_id.lower() not in ("none", "null", "nan", "0"):
                    key = (ord_id, sym)
                else:
                    anon_seq += 1
                    key = (f"__row_{anon_seq}", sym)

                if key not in grouped_closes:
                    grouped_closes[key] = {
                        "ts": ts_dt,
                        "pnl": 0.0,
                        "close_fee": 0.0,
                        "in_7d": ts_dt >= cutoff_7d,
                    }
                    close_order.append(key)
                grouped_closes[key]["pnl"] += pnl
                grouped_closes[key]["close_fee"] += fee
                if ts_dt >= cutoff_7d:
                    grouped_closes[key]["in_7d"] = True
    except Exception as exc:
        _log(f"⚠️ CSV 파싱 오류 ({csv_path}): {exc}")
        return result

    cur_streak = 0
    max_streak = 0
    for key in sorted(close_order, key=lambda k: grouped_closes[k]["ts"]):
        item = grouped_closes[key]
        pnl = item["pnl"]
        result["closed_trades_all"] += 1
        result["gross_pnl_all"] += pnl
        if item["in_7d"]:
            result["closed_trades_7d"] += 1
            result["gross_pnl_7d"] += pnl

        # 청산가 기준 수익(또는 손익) 판별: 순수 가격차익 기준 손실(< 0) 시 연패 증가
        if pnl > 0:
            result["wins_all"] += 1
            cur_streak = 0
        elif pnl < 0:
            result["losses_all"] += 1
            cur_streak += 1
            if cur_streak > max_streak:
                max_streak = cur_streak

    result["gross_pnl_all"] = round(result["gross_pnl_all"], 4)
    result["fees_all"] = round(result["fees_all"], 4)
    result["net_pnl_all"] = round(result["gross_pnl_all"] - result["fees_all"], 4)
    result["gross_pnl_7d"] = round(result["gross_pnl_7d"], 4)
    result["fees_7d"] = round(result["fees_7d"], 4)
    result["net_pnl_7d"] = round(result["gross_pnl_7d"] - result["fees_7d"], 4)
    result["cur_loss_streak"] = cur_streak
    result["max_loss_streak"] = max_streak

    if result["closed_trades_all"] > 0:
        if result["gross_pnl_all"] > 0:
            result["fee_ratio_all_pct"] = round(
                (result["fees_all"] / result["gross_pnl_all"]) * 100.0, 1
            )
        elif result["fees_all"] > 0:
            result["fee_deficit_all"] = True
        else:
            result["fee_ratio_all_pct"] = 0.0

    if result["closed_trades_7d"] > 0:
        if result["gross_pnl_7d"] > 0:
            result["fee_ratio_7d_pct"] = round(
                (result["fees_7d"] / result["gross_pnl_7d"]) * 100.0, 1
            )
        elif result["fees_7d"] > 0:
            result["fee_deficit_7d"] = True
        else:
            result["fee_ratio_7d_pct"] = 0.0

    return result


def _fetch_live_8888_balances(timeout_sec=20):
    """data/live_balances.json(거래소 실측 캐시, <=300s) 또는 8888 /api/status에서 실시간 잔고를 조회한다."""
    doc = _load_json(LIVE_BALANCES_PATH, {}) or {}
    ts_epoch = _safe_float(doc.get("ts"), 0.0)
    bots_map = doc.get("bots") or {}
    if bots_map and ts_epoch > 0 and (time.time() - ts_epoch) <= 300:
        live = {}
        for bid, val in bots_map.items():
            fv = _safe_float(val, 0.0)
            if fv > 0:
                live[str(bid)] = fv
        if live:
            return live

    live = {}
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8888/api/status", timeout=timeout_sec)
        data = json.loads(req.read().decode("utf-8"))
        for b in data.get("bots") or []:
            bid = str(b.get("name") or "")
            bal = _safe_float(b.get("ex_balance"), 0.0)
            if bid and b.get("ex_ok") and bal > 0:
                live[bid] = bal
    except Exception:
        pass
    return live


def _eval_bot(bot_id, bot_baseline, live_ex_bots, latest_snap_bots, peak_assets_map, now_dt):
    bot_dir = os.path.join(PROJECT_ROOT, bot_id)
    if os.path.exists(os.path.join(bot_dir, ".stopped")):
        return None

    stats = _load_json(os.path.join(bot_dir, "data", "stats.json"), {}) or {}
    cfg = _load_json(os.path.join(bot_dir, "config.json"), {}) or {}
    backtest = bot_baseline.get("backtest", {})
    thresholds = bot_baseline.get("thresholds", {})
    tier = int(bot_baseline.get("approval_tier", 2))
    tier_label = "5회 승인 필수" if tier >= 5 else "2회 승인 필수"

    seed = _safe_float(stats.get("seed_money"), 0.0)
    perf_start_str = stats.get("perf_start_time")
    perf_start_dt = _parse_dt(perf_start_str)
    sample_days = 0.0
    if perf_start_dt:
        sample_days = round(max(0.0, (now_dt - perf_start_dt).total_seconds() / 86400.0), 1)

    trade_stats = _analyze_trade_history(
        os.path.join(bot_dir, "data", "trade_history.csv"), perf_start_dt, now_dt
    )

    live_bal = live_ex_bots.get(bot_id)
    snap_bal = latest_snap_bots.get(bot_id)
    if live_bal is not None and _safe_float(live_bal, 0.0) > 0:
        current_asset = round(_safe_float(live_bal, 0.0), 4)
        asset_source = "exchange_live"
    elif seed > 0:
        current_asset = round(seed + _safe_float(trade_stats.get("net_pnl_all"), 0.0), 4)
        asset_source = "csv_net_fallback"
    elif snap_bal is not None and _safe_float(snap_bal, 0.0) > 0:
        current_asset = round(_safe_float(snap_bal, 0.0), 4)
        asset_source = "snapshot_fallback"
    else:
        current_asset = None
        asset_source = "unknown"

    peak_entry = peak_assets_map.get(bot_id) or {}
    raw_peak = _safe_float(peak_entry.get("peak_asset"), 0.0)
    peak_ts = peak_entry.get("peak_ts")
    if current_asset is not None and current_asset > raw_peak:
        peak_asset = round(current_asset, 4)
        peak_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    elif raw_peak > 0:
        peak_asset = round(raw_peak, 4)
    else:
        peak_asset = current_asset

    peak_dd_pct = None
    abs_peak_dd = 0.0
    if peak_asset and peak_asset > 0 and current_asset is not None:
        raw_dd = ((current_asset - peak_asset) / peak_asset) * 100.0
        peak_dd_pct = round(min(0.0, raw_dd), 2)
        abs_peak_dd = round(max(0.0, -peak_dd_pct), 2)

    active_alerts = []

    # 1) Peak-to-Current MDD vs Survival Thresholds
    mdd_warn = float(thresholds.get("peak_mdd_warn_pct", 12.0))
    mdd_kill = float(thresholds.get("peak_mdd_kill_pct", 20.0))
    if peak_dd_pct is not None and abs_peak_dd >= mdd_kill:
        msg = (
            f"전고점(${peak_asset:.2f}, {peak_ts or '?'}) 대비 현재자산 ${current_asset:.2f} "
            f"({peak_dd_pct:.2f}% / 허용 킬선 -{mdd_kill:.1f}% 초과)"
        )
        rec = (
            f"[{tier_label}] 봇 진입 일시중단 또는 전략·비중({bot_baseline.get('strategy_id')}) "
            f"파라미터 전면 재조정 승인을 요청합니다."
        )
        record_proactive_alert(
            bot_id, "peak_mdd", "CRITICAL", f"Peak-MDD 한계 초과 ({peak_dd_pct:.1f}%)",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "peak_mdd", "severity": "CRITICAL", "title": f"Peak-MDD 한계 초과 ({peak_dd_pct:.1f}%)"})
    elif peak_dd_pct is not None and abs_peak_dd >= mdd_warn:
        msg = (
            f"전고점(${peak_asset:.2f}) 대비 현재자산 ${current_asset:.2f} "
            f"({peak_dd_pct:.2f}% / 주의 -{mdd_warn:.1f}%, 킬선 -{mdd_kill:.1f}%)"
        )
        rec = f"[{tier_label}] 추가 하락 시 킬선(-{mdd_kill:.1f}%) 도달 예정. 비중 축소 및 리스크 한도 검토 권고."
        record_proactive_alert(
            bot_id, "peak_mdd", "WARN", f"Peak-MDD 주의 구간 ({peak_dd_pct:.1f}%)",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "peak_mdd", "severity": "WARN", "title": f"Peak-MDD 주의 구간 ({peak_dd_pct:.1f}%)"})
    else:
        clear_proactive_alert(bot_id, "peak_mdd")

    # 2) Fee-to-Gross Ratio Monitoring (누적 기준 우선 + 7d 충분표본 보조 감시)
    fee_warn = float(thresholds.get("max_fee_ratio_warn_pct", 50.0))
    fee_kill = float(thresholds.get("max_fee_ratio_kill_pct", 100.0))
    fr_7d = trade_stats["fee_ratio_7d_pct"]
    fr_all = trade_stats["fee_ratio_all_pct"]
    fd_7d = bool(trade_stats.get("fee_deficit_7d"))
    fd_all = bool(trade_stats.get("fee_deficit_all"))
    closed_7d = trade_stats["closed_trades_7d"]
    closed_all = trade_stats["closed_trades_all"]

    fr_7d_txt = "적자(Gross<=0)" if fd_7d else (f"{fr_7d:.1f}%" if fr_7d is not None else "—")
    fr_all_txt = "적자(Gross<=0)" if fd_all else (f"{fr_all:.1f}%" if fr_all is not None else "—")

    if closed_all >= 20 and (fd_all or (fr_all is not None and fr_all >= fee_kill)):
        lbl = "Gross<=0 적자" if fd_all else f"{fr_all:.0f}%"
        msg = (
            f"누적 수수료 비중 {fr_all_txt} (누적 Gross ${trade_stats['gross_pnl_all']:+.2f}/Fee ${trade_stats['fees_all']:.2f}, "
            f"7d {fr_7d_txt} Gross ${trade_stats['gross_pnl_7d']:+.2f}/Fee ${trade_stats['fees_7d']:.2f})"
        )
        rec = f"[{tier_label}] 수익 대비 수수료 잠식 >=100%. 타임프레임 상향·필터 강화 또는 전략 교체 검토를 요청합니다."
        record_proactive_alert(
            bot_id, "fee_ratio", "CRITICAL", f"누적 수수료 적자 ({lbl})",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "fee_ratio", "severity": "CRITICAL", "title": f"수수료 적자 ({lbl})"})
    elif (closed_all >= 20 and fr_all is not None and fr_all >= fee_warn) or (
        closed_7d >= 20 and (fd_7d or (fr_7d is not None and fr_7d >= fee_kill))
    ):
        pct_str = f"누적 {fr_all:.0f}%" if (fr_all is not None and fr_all >= fee_warn) else f"7d {fr_7d_txt}"
        msg = (
            f"수수료 비중 주의 ({pct_str} | 7d {fr_7d_txt} Fee ${trade_stats['fees_7d']:.2f} / "
            f"누적 {fr_all_txt} Fee ${trade_stats['fees_all']:.2f})"
        )
        rec = f"[{tier_label}] 수수료 잠식 심화. 메이커 지정가 비중 확대 또는 진입 필터 보강 검토 권고."
        record_proactive_alert(
            bot_id, "fee_ratio", "WARN", f"수수료 비중 주의 ({pct_str})",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "fee_ratio", "severity": "WARN", "title": f"수수료 비중 주의 ({pct_str})"})
    else:
        clear_proactive_alert(bot_id, "fee_ratio")

    # 3) Active Loss Streak vs Expected Max Loss Streak
    ls_warn = int(thresholds.get("max_loss_streak_warn", 8))
    ls_kill = int(thresholds.get("max_loss_streak_kill", 12))
    cur_ls = int(trade_stats["cur_loss_streak"])
    max_ls = int(trade_stats["max_loss_streak"])
    if cur_ls >= ls_kill:
        msg = f"현재 {cur_ls}연패 진행 중 (역대 기대 한계 {ls_kill}연패 도달/초과)"
        rec = f"[{tier_label}] 5년 백테스트 최대 연패 한계 도달. 레짐 이상 또는 전략 수명 종료 여부 점검 승인을 요청합니다."
        record_proactive_alert(
            bot_id, "loss_streak", "CRITICAL", f"최대 연패 임계 초과 ({cur_ls}연패)",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "loss_streak", "severity": "CRITICAL", "title": f"{cur_ls}연패 임계 초과"})
    elif cur_ls >= ls_warn:
        msg = f"현재 {cur_ls}연패 진행 중 (주의 {ls_warn}연패 이상, 킬선 {ls_kill}연패)"
        rec = f"[{tier_label}] 연패 비중 축소(USE_DYNAMIC_REGIME) 동작 여부 및 손실 진행 점검 권고."
        record_proactive_alert(
            bot_id, "loss_streak", "WARN", f"연패 주의 구간 ({cur_ls}연패)",
            msg, recommendation=rec, cooldown_sec=21600, notify_discord=True
        )
        active_alerts.append({"key": "loss_streak", "severity": "WARN", "title": f"{cur_ls}연패 주의"})
    else:
        clear_proactive_alert(bot_id, "loss_streak")

    # 4) Sample Observation Milestones (30d / 60d)
    min_days = int(thresholds.get("min_sample_days", 30))
    target_days = int(thresholds.get("review_target_days", 60))
    if sample_days >= target_days:
        msg = f"운용 표본 {sample_days:.1f}일 / 청산 {closed_all}건 (목표 검증 {target_days}일 도달)"
        rec = f"[{tier_label}] 충분한 표본 확보 완료. 순/역 자동스위칭 및 전략 유지/개선 최종 판정 보고 권고."
        record_proactive_alert(
            bot_id, "sample_review", "WARN", f"표본 {sample_days:.0f}일 도달 (최종 검토 시점)",
            msg, recommendation=rec, cooldown_sec=86400, notify_discord=True
        )
        active_alerts.append({"key": "sample_review", "severity": "WARN", "title": f"표본 {sample_days:.0f}일 도달"})
    elif sample_days >= min_days:
        msg = f"운용 표본 {sample_days:.1f}일 / 청산 {closed_all}건 (최소 {min_days}일 충족, 목표 {target_days}일)"
        rec = f"[{tier_label}] 최소 표본 충족 — 백테스트 기대치 대비 중간 성과 비교 가능."
        record_proactive_alert(
            bot_id, "sample_review", "INFO", f"최소 표본 {min_days}일 충족 ({sample_days:.1f}일)",
            msg, recommendation=rec, cooldown_sec=86400, notify_discord=False
        )
        active_alerts.append({"key": "sample_review", "severity": "INFO", "title": f"표본 {sample_days:.0f}일 충족"})
    else:
        clear_proactive_alert(bot_id, "sample_review")

    # 5) Survival Config Gaps (Read-Only Detection + Approval Request)
    gaps = []
    cfg_mdd = _safe_float(cfg.get("MAX_DRAWDOWN_PCT"), 0.5)
    rec_mdd = float(thresholds.get("recommend_max_drawdown_pct", 0.20))
    if cfg_mdd >= 0.45:
        gaps.append(f"MAX_DRAWDOWN_PCT={cfg_mdd:.2f}(초기자본-50% 방치 → 고점기준 -{rec_mdd*100:.0f}% 킬스위치 필요)")

    cfg_dll = _safe_float(cfg.get("DAILY_LOSS_LIMIT_USDT"), 999.0)
    ref_cap = max(seed, current_asset or 0.0, 10.0)
    if cfg_dll >= 500.0 or cfg_dll > ref_cap * 0.25:
        rec_dll = round(ref_cap * float(thresholds.get("recommend_daily_loss_limit_pct_of_seed", 0.06)), 2)
        gaps.append(f"DAILY_LOSS_LIMIT_USDT={cfg_dll:.0f}(실질 무력 → 약 ${rec_dll:.2f} 현실화 필요)")

    if bool(thresholds.get("require_dynamic_regime", True)) and not bool(cfg.get("USE_DYNAMIC_REGIME", False)):
        gaps.append("USE_DYNAMIC_REGIME=False(연패 시 비중 50% 축소 미작동)")

    risk_pct = _safe_float(cfg.get("RISK_PER_TRADE_PCT"), 0.0)
    comp_pct = _safe_float(cfg.get("AUTO_COMPOUND_PCT"), 0.0)
    if risk_pct == 0.0 and comp_pct >= 0.25:
        gaps.append(f"M4 리스크사이징 미적용(RISK_PER_TRADE_PCT=0, AUTO_COMPOUND_PCT={comp_pct})")

    if bot_id == "8402" and int(_safe_float(cfg.get("MAX_POSITIONS"), 3)) > 2:
        gaps.append(f"MAX_POSITIONS={int(_safe_float(cfg.get('MAX_POSITIONS'), 3))}(8401 동급 2개 일치 필요)")

    if gaps:
        msg = "생존 안전장치 미비 항목: " + " | ".join(gaps)
        rec = f"[{tier_label}] 봇 소스/설정 임의 수정은 금지되어 있습니다. Phase 3 승인 절차로 반영 요청 중."
        record_proactive_alert(
            bot_id, "config_gap", "WARN", f"생존 설정 미비 {len(gaps)}건 감지",
            msg, recommendation=rec, cooldown_sec=43200, notify_discord=True
        )
        active_alerts.append({"key": "config_gap", "severity": "WARN", "title": f"생존 설정 {len(gaps)}건 미비"})
    else:
        clear_proactive_alert(bot_id, "config_gap")

    return {
        "bot_id": bot_id,
        "strategy_id": bot_baseline.get("strategy_id"),
        "timeframe": cfg.get("TIMEFRAME") or bot_baseline.get("timeframe"),
        "approval_tier": tier,
        "approval_label": tier_label,
        "seed_money": round(seed, 4),
        "current_asset": current_asset,
        "asset_source": asset_source,
        "peak_asset": peak_asset,
        "peak_ts": peak_ts,
        "peak_dd_pct": peak_dd_pct,
        "expected_mdd_pct": backtest.get("expected_mdd_pct"),
        "peak_mdd_warn_pct": mdd_warn,
        "peak_mdd_kill_pct": mdd_kill,
        "sample_days": sample_days,
        "min_sample_days": min_days,
        "review_target_days": target_days,
        "closed_trades": closed_all,
        "closed_trades_7d": closed_7d,
        "gross_pnl_all": trade_stats["gross_pnl_all"],
        "fees_all": trade_stats["fees_all"],
        "fee_ratio_all_pct": fr_all,
        "fee_deficit_all": fd_all,
        "gross_pnl_7d": trade_stats["gross_pnl_7d"],
        "fees_7d": trade_stats["fees_7d"],
        "fee_ratio_7d_pct": fr_7d,
        "fee_deficit_7d": fd_7d,
        "cur_loss_streak": cur_ls,
        "max_loss_streak": max_ls,
        "expected_max_loss_streak": backtest.get("expected_max_loss_streak"),
        "max_loss_streak_warn": ls_warn,
        "max_loss_streak_kill": ls_kill,
        "config_gaps": gaps,
        "active_alerts": active_alerts,
        "checked_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def run_once():
    now_dt = datetime.now()
    baselines_doc = _load_json(BASELINES_PATH, {}) or {}
    bots_baselines = baselines_doc.get("bots", {})
    peak_assets_map = _load_json(PEAK_ASSETS_PATH, {}) or {}
    live_ex_bots = _fetch_live_8888_balances()
    snapshots = _load_json(SNAPSHOTS_PATH, []) or []
    latest_snap_bots = {}
    if isinstance(snapshots, list) and snapshots:
        last_snap = snapshots[-1]
        if isinstance(last_snap, dict):
            latest_snap_bots = last_snap.get("bots") or {}

    status_bots = {}
    all_alerts_summary = []
    for bot_id in ACTIVE_BOTS:
        bot_bl = bots_baselines.get(bot_id)
        if not bot_bl:
            continue
        res = _eval_bot(bot_id, bot_bl, live_ex_bots, latest_snap_bots, peak_assets_map, now_dt)
        if res is None:
            continue
        status_bots[bot_id] = res
        if res["active_alerts"]:
            titles = ", ".join(a["title"] for a in res["active_alerts"])
            all_alerts_summary.append(f"{bot_id}: {titles}")

    payload = {
        "updated": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "baselines_version": (baselines_doc.get("_meta") or {}).get("version", "1.0.0"),
        "bots": status_bots,
        "proactive_alerts_snapshot": load_proactive_alerts().get("active", {}),
    }
    _atomic_save_json(LIFECYCLE_STATUS_PATH, payload)

    if all_alerts_summary:
        _log(f"📊 수명·임계치 점검 완료 (경고/제안 {len(all_alerts_summary)}봇): " + " | ".join(all_alerts_summary))
    else:
        _log("✅ 전 봇 수명·임계치 점검 완료 — 이상 없음")
    return payload


def main():
    parser = argparse.ArgumentParser(description="8888 Proactive Strategy Lifecycle Monitor")
    parser.add_argument("--once", action="store_true", help="Run a single lifecycle inspection cycle and exit")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    lock_fd = open(LOCK_PATH, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _log("⚠️ watchdog_profitability.py 이미 실행 중 (fcntl.flock 충돌) — 중복 기동 종료")
        return
    lock_fd.write(f"{os.getpid()}\n")
    lock_fd.flush()

    _log(f"🛡️ watchdog_profitability.py 가동 (PID {os.getpid()}, Read-Only 사전감시 모드, 주기 {CHECK_INTERVAL_SEC}s)")
    while True:
        try:
            run_once()
        except Exception as exc:
            _log(f"❌ 점검 루프 예외: {exc}")
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()
