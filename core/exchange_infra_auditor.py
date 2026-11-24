#!/usr/bin/env python3
"""
8888 — Exchange & Infrastructure Autonomous Auditor (`core/exchange_infra_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers Aegis V6 modules (Read-Only detection + alert/rotation, NEVER mutates bot configs):
  - M17: Exchange Maintenance (OKX system/status filtered for futures/trading, NOT copy-trading),
         Delisting / Contract Expiry / Leverage Tier & Spec changes (OKX + Binance)
  - M18: System Clock Drift (ms) & Exchange API RTT Latency + HTTP 429 / RateLimit spikes
  - M20: Funding Rate Extremes & Short-Interval Drain for currently held positions
  - M23: API Key Auth/IP Failure Log Scan (-2015, 50111, 50113, 401/403) + TTL Expiry Check
  - M24: Host Disk, Process RSS, Long-running Orphan Helpers, Open FD & Safe Copy-Truncate Rotation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    http_get_json,
    rotate_log_copytruncate,
)

INFRA_HEALTH_FILE = os.path.join(BASE_8888, "data", "infra_health.json")
EXCHANGE_META_CACHE_FILE = os.path.join(BASE_8888, "data", "exchange_meta_cache.json")
API_KEY_META_FILE = os.path.join(BASE_8888, "data", "api_key_meta.json")
SENTINEL_CACHE_FILE = os.path.join(BASE_8888, "data", "sentinel_live_cache.json")

# OKX serviceType values representing actual swap/trading/WS (excludes e.g. '11' Copy Trading)
_OKX_TRADING_SERVICE_TYPES = {"0", "1", "2", "3", "4", "5", "6", "7", "8"}

_RATE_LIMIT_RE = re.compile(r"(429|ratelimit|rate limit|too many requests|-1003|-1015)", re.I)
_AUTH_ERR_RE = re.compile(
    r"(-2015|50111|50113|invalid api[- ]?key|ip not in whitelist|api[- ]?key expired|401 unauthorized|403 forbidden|invalid sign)",
    re.I,
)


def _load_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _sym_to_okx_inst(sym: str) -> str:
    base_quote = str(sym or "").split(":")[0].strip()
    if "/" in base_quote:
        return base_quote.replace("/", "-") + "-SWAP"
    return base_quote


def _sym_to_binance_inst(sym: str) -> str:
    base_quote = str(sym or "").split(":")[0].strip()
    return base_quote.replace("/", "").replace("-", "")


def _collect_bot_symbols(bots: List[int]) -> Dict[str, Dict[str, Any]]:
    """Gather exchange, leverage, whitelist symbols, and active positions per bot."""
    info: Dict[str, Dict[str, Any]] = {}
    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if not os.path.isdir(bdir) or os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        act = _load_json(os.path.join(bdir, "data", "active_positions.json"), {}) or {}
        ex = str(cfg.get("EXCHANGE_ID", "okx" if int(b) <= 8405 else "binance")).lower()
        lev = int(float(cfg.get("LEVERAGE", 3) or 3))
        wl = cfg.get("SYMBOL_WHITELIST") or cfg.get("SYMBOLS") or []
        if not isinstance(wl, list):
            wl = []
        act_syms = list(act.keys()) if isinstance(act, dict) else []
        info[bs] = {
            "exchange": ex,
            "leverage": lev,
            "whitelist": wl,
            "active_symbols": act_syms,
            "all_symbols": sorted(set(wl) | set(act_syms)),
        }
    return info


def check_exchange_maintenance_and_listings(bots: List[int], include_listings: bool = True) -> Dict[str, Any]:
    """
    [M17] Check OKX system/status maintenance, OKX SWAP instruments, Binance futures exchangeInfo
    for delisting/expiry/spec/leverage-tier mismatches across all bot whitelists & active positions.
    """
    alerts: List[Dict[str, str]] = []
    details: Dict[str, Any] = {
        "okx_maintenance": [],
        "delisting_or_missing": [],
        "leverage_tier_issues": [],
        "spec_changes": [],
        "checked_listings": bool(include_listings),
    }

    # 1) OKX Maintenance Status
    okx_status, okx_err = http_get_json("https://www.okx.com/api/v5/system/status", timeout=5.0)
    if okx_status and str(okx_status.get("code")) == "0":
        for row in (okx_status.get("data") or []):
            stype = str(row.get("serviceType") or "")
            state = str(row.get("state") or "").lower()
            title = str(row.get("title") or "")
            # Filter out unrelated copy-trading / earn services
            if state in ("ongoing", "scheduled") and stype in _OKX_TRADING_SERVICE_TYPES:
                details["okx_maintenance"].append({"state": state, "serviceType": stype, "title": title})
                sev = "CRITICAL" if state == "ongoing" else "WARN"
                alerts.append({
                    "bot_id": "8888",
                    "key": "infra_exchange_maintenance",
                    "severity": sev,
                    "title": f"OKX 거래시스템 점검 감지 ({state})",
                    "details": f"serviceType={stype}, title={title}",
                    "recommendation": "거래소 점검 중 API 오류 및 강제취소 발생 가능 — 주문 상태 예의주시 필요",
                })
    elif okx_err:
        details["okx_status_error"] = okx_err

    if not include_listings:
        return {"alerts": alerts, "details": details}

    bot_map = _collect_bot_symbols(bots)
    okx_needed = any(v["exchange"] == "okx" for v in bot_map.values())
    bnc_needed = any(v["exchange"] == "binance" for v in bot_map.values())

    meta_cache = _load_json(EXCHANGE_META_CACHE_FILE, {}) or {}
    new_meta_cache = dict(meta_cache)
    now_ms = time.time() * 1000.0
    seven_days_ms = 7 * 86400 * 1000.0

    okx_insts: Dict[str, dict] = {}
    if okx_needed:
        okx_res, o_err = http_get_json("https://www.okx.com/api/v5/public/instruments?instType=SWAP", timeout=8.0)
        if okx_res and str(okx_res.get("code")) == "0":
            for it in (okx_res.get("data") or []):
                iid = str(it.get("instId") or "")
                if iid:
                    okx_insts[iid] = it
        elif o_err:
            details["okx_instruments_error"] = o_err

    bnc_insts: Dict[str, dict] = {}
    if bnc_needed:
        bnc_res, b_err = http_get_json("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=8.0)
        if bnc_res and isinstance(bnc_res.get("symbols"), list):
            for it in bnc_res["symbols"]:
                sid = str(it.get("symbol") or "")
                if sid:
                    bnc_insts[sid] = it
        elif b_err:
            details["binance_exchangeinfo_error"] = b_err

    for bs, binfo in bot_map.items():
        ex = binfo["exchange"]
        lev = binfo["leverage"]
        active_set = set(binfo["active_symbols"])

        if ex == "okx" and okx_insts:
            for sym in binfo["all_symbols"]:
                iid = _sym_to_okx_inst(sym)
                it = okx_insts.get(iid)
                is_act = sym in active_set
                if not it:
                    details["delisting_or_missing"].append(f"{bs}:okx:{iid}:MISSING")
                    if is_act:
                        alerts.append({
                            "bot_id": bs,
                            "key": "infra_delisting_risk",
                            "severity": "CRITICAL",
                            "title": f"OKX 보유 종목 상장정보 누락 ({iid})",
                            "details": f"{bs}봇 보유 중 심볼 {sym}이 OKX SWAP live 목록에서 미발견",
                            "recommendation": "즉시 거래소 공지 및 포지션 정산 여부 확인 필요",
                        })
                    continue

                st = str(it.get("state") or "").lower()
                exp_str = str(it.get("expTime") or "").strip()
                exp_ms = int(exp_str) if exp_str.isdigit() else 0
                if st != "live" or (0 < exp_ms - now_ms <= seven_days_ms):
                    details["delisting_or_missing"].append(f"{bs}:okx:{iid}:state={st}:exp={exp_str}")
                    alerts.append({
                        "bot_id": bs,
                        "key": "infra_delisting_risk",
                        "severity": "CRITICAL" if (is_act or st != "live") else "WARN",
                        "title": f"OKX 계약 상태/만기 경보 ({iid})",
                        "details": f"state={st}, expTime={exp_str or 'N/A'}, active={is_act}",
                        "recommendation": f"[{bs}봇] 상장폐지/정산 전환 종목 포지션 정리 및 화이트리스트 제외 검토 요청",
                    })

                try:
                    max_lev = float(it.get("lever") or 0)
                    if 0 < max_lev < lev:
                        details["leverage_tier_issues"].append(f"{bs}:{iid}:maxLev={max_lev}<cfg={lev}")
                        alerts.append({
                            "bot_id": bs,
                            "key": "infra_leverage_tier",
                            "severity": "CRITICAL",
                            "title": f"OKX 최대 레버리지 하향 감지 ({iid})",
                            "details": f"거래소 상한 {max_lev}x < 봇 설정 {lev}x",
                            "recommendation": f"[{bs}봇] 레버리지 축소 승인 또는 종목 제외 검토 필요",
                        })
                except (TypeError, ValueError):
                    pass

                spec_sig = f"okx:{iid}:ctVal={it.get('ctVal')}:minSz={it.get('minSz')}:lotSz={it.get('lotSz')}:tickSz={it.get('tickSz')}"
                prev_sig = meta_cache.get(f"okx:{iid}")
                if prev_sig and prev_sig != spec_sig:
                    details["spec_changes"].append(f"{iid}: {prev_sig} -> {spec_sig}")
                new_meta_cache[f"okx:{iid}"] = spec_sig

        elif ex == "binance" and bnc_insts:
            for sym in binfo["all_symbols"]:
                sid = _sym_to_binance_inst(sym)
                it = bnc_insts.get(sid)
                is_act = sym in active_set
                if not it:
                    details["delisting_or_missing"].append(f"{bs}:binance:{sid}:MISSING")
                    if is_act:
                        alerts.append({
                            "bot_id": bs,
                            "key": "infra_delisting_risk",
                            "severity": "CRITICAL",
                            "title": f"Binance 보유 종목 상장정보 누락 ({sid})",
                            "details": f"{bs}봇 보유 중 심볼 {sym}이 Binance Futures exchangeInfo에서 미발견",
                            "recommendation": "즉시 거래소 공지 및 포지션 정산 여부 확인 필요",
                        })
                    continue

                st = str(it.get("status") or "").upper()
                deliv = int(it.get("deliveryDate") or 0)
                # Binance perpetuals normally use year 2100+ deliveryDate (~4133404800000); <4000000000000 means real expiry
                soon_expiry = 0 < deliv < 4000000000000 and (deliv - now_ms) <= seven_days_ms
                if st != "TRADING" or soon_expiry:
                    details["delisting_or_missing"].append(f"{bs}:binance:{sid}:status={st}:deliv={deliv}")
                    alerts.append({
                        "bot_id": bs,
                        "key": "infra_delisting_risk",
                        "severity": "CRITICAL" if (is_act or st != "TRADING") else "WARN",
                        "title": f"Binance 계약 상태/만기 경보 ({sid})",
                        "details": f"status={st}, deliveryDate={deliv}, active={is_act}",
                        "recommendation": f"[{bs}봇] 상장폐지/정산 전환 종목 포지션 정리 및 화이트리스트 제외 검토 요청",
                    })

                lot_f = next((f for f in (it.get("filters") or []) if f.get("filterType") == "LOT_SIZE"), {})
                min_f = next((f for f in (it.get("filters") or []) if f.get("filterType") == "MIN_NOTIONAL"), {})
                spec_sig = f"bnc:{sid}:step={lot_f.get('stepSize')}:minQty={lot_f.get('minQty')}:minNot={min_f.get('notional')}"
                prev_sig = meta_cache.get(f"bnc:{sid}")
                if prev_sig and prev_sig != spec_sig:
                    details["spec_changes"].append(f"{sid}: {prev_sig} -> {spec_sig}")
                new_meta_cache[f"bnc:{sid}"] = spec_sig

    if details["spec_changes"]:
        alerts.append({
            "bot_id": "8888",
            "key": "infra_contract_spec_changed",
            "severity": "WARN",
            "title": f"거래소 계약 규격 변경 감지 ({len(details['spec_changes'])}건)",
            "details": " | ".join(details["spec_changes"][:5]),
            "recommendation": "최소주문수량(minSz/minQty) 또는 명목가 한도 영향 여부 점검 권고",
        })

    try:
        _atomic_write_json(EXCHANGE_META_CACHE_FILE, new_meta_cache)
    except Exception:
        pass

    return {"alerts": alerts, "details": details}


def check_clock_drift_and_latency(bots: List[int]) -> Dict[str, Any]:
    """[M18] Measure system clock drift vs OKX/Binance server time, RTT, and 5m HTTP 429 spikes."""
    alerts: List[Dict[str, str]] = []
    venues: Dict[str, Dict[str, Any]] = {}

    for venue, url, extractor in (
        ("okx", "https://www.okx.com/api/v5/public/time", lambda d: int(d["data"][0]["ts"])),
        ("binance", "https://fapi.binance.com/fapi/v1/time", lambda d: int(d["serverTime"])),
    ):
        t0 = time.time() * 1000.0
        data, err = http_get_json(url, timeout=5.0)
        t1 = time.time() * 1000.0
        rtt_ms = round(t1 - t0, 1)
        if data is not None:
            try:
                srv_ms = extractor(data)
                drift_ms = round(((t0 + t1) / 2.0) - srv_ms, 1)
                venues[venue] = {"ok": True, "rtt_ms": rtt_ms, "clock_drift_ms": drift_ms}
                abs_drift = abs(drift_ms)
                # Binance rejects +1000ms ahead immediately; behind allows up to recvWindow (5000ms)
                if drift_ms > 850 or abs_drift > 4000 or rtt_ms > 2000:
                    alerts.append({
                        "bot_id": "8888",
                        "key": f"infra_clock_latency_{venue}",
                        "severity": "CRITICAL",
                        "title": f"{venue.upper()} 시계 오차/지연 심각",
                        "details": f"clock_drift={drift_ms:+.1f}ms, rtt={rtt_ms:.1f}ms",
                        "recommendation": "macOS NTP 시계 동기화(sntp) 및 네트워크 상태 즉시 점검 필요",
                    })
                elif abs_drift > 1500 or rtt_ms > 800:
                    alerts.append({
                        "bot_id": "8888",
                        "key": f"infra_clock_latency_{venue}",
                        "severity": "WARN",
                        "title": f"{venue.upper()} 시계 오차/지연 주의",
                        "details": f"clock_drift={drift_ms:+.1f}ms, rtt={rtt_ms:.1f}ms",
                        "recommendation": "API 서명 오차(-1021/50102) 예방을 위해 시계/지연 추이 주시",
                    })
            except Exception as e:
                venues[venue] = {"ok": False, "rtt_ms": rtt_ms, "error": str(e)}
        else:
            venues[venue] = {"ok": False, "rtt_ms": rtt_ms, "error": err}

    # Scan recent 5m engine logs for HTTP 429 / rate limits
    now_local = datetime.now()
    cutoff = now_local - timedelta(minutes=5)
    rl_counts: Dict[str, int] = {}
    for b in bots:
        bs = str(b)
        lp = os.path.join(BASE_PROJECT, bs, "bot_engine.log")
        if not os.path.exists(lp):
            continue
        cnt = 0
        try:
            with open(lp, "rb") as f:
                f.seek(0, os.SEEK_END)
                sz = f.tell()
                f.seek(max(0, sz - 65536))
                chunk = f.read().decode("utf-8", errors="ignore")
            for line in chunk.splitlines():
                if len(line) >= 19:
                    try:
                        ldt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                        if ldt < cutoff:
                            continue
                    except ValueError:
                        pass
                if _RATE_LIMIT_RE.search(line):
                    cnt += 1
        except Exception:
            pass
        if cnt > 0:
            rl_counts[bs] = cnt
        if cnt >= 10:
            alerts.append({
                "bot_id": bs,
                "key": "infra_rate_limit",
                "severity": "CRITICAL",
                "title": f"HTTP 429/RateLimit 폭증 ({cnt}회/5분)",
                "details": f"최근 5분 내 Rate Limit 관련 로그 {cnt}회 누적 — IP 차단 위험",
                "recommendation": f"[{bs}봇] 스캔 주기 또는 API 동시 호출 제한 점검 필요",
            })
        elif cnt >= 3:
            alerts.append({
                "bot_id": bs,
                "key": "infra_rate_limit",
                "severity": "WARN",
                "title": f"HTTP 429/RateLimit 반복 ({cnt}회/5분)",
                "details": f"최근 5분 내 Rate Limit 로그 {cnt}회 관측",
                "recommendation": "거래소 API 가중치 여유분 추이 확인 권고",
            })

    return {"alerts": alerts, "details": {"venues": venues, "rate_limit_5m": rl_counts}}


def check_funding_rates_for_positions(bots: List[int]) -> Dict[str, Any]:
    """[M20] Check live funding rates against open positions across all active bots."""
    alerts: List[Dict[str, str]] = []
    cache = _load_json(SENTINEL_CACHE_FILE, {}) or {}
    cache_bots = cache.get("bots") or {}
    bot_map = _collect_bot_symbols(bots)

    positions_to_check: List[Tuple[str, str, str, str]] = []  # (bot_id, exchange, sym, side)
    for bs, binfo in bot_map.items():
        ex = binfo["exchange"]
        centry = cache_bots.get(bs) or {}
        cpos = centry.get("positions") or []
        if cpos and (time.time() - float(centry.get("ts") or 0.0)) <= 900:
            for p in cpos:
                if p.get("symbol") and p.get("side"):
                    positions_to_check.append((bs, ex, str(p["symbol"]), str(p["side"]).lower()))
        else:
            act = _load_json(os.path.join(BASE_PROJECT, bs, "data", "active_positions.json"), {}) or {}
            if isinstance(act, dict):
                for sym, meta in act.items():
                    side = str((meta or {}).get("side") or "").lower()
                    if side in ("long", "short"):
                        positions_to_check.append((bs, ex, sym, side))

    funding_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    observed: List[Dict[str, Any]] = []

    for bs, ex, sym, side in positions_to_check:
        ck = (ex, sym)
        if ck not in funding_cache:
            rec = {"rate": None, "interval_h": 8.0, "error": ""}
            if ex == "okx":
                iid = _sym_to_okx_inst(sym)
                res, err = http_get_json(f"https://www.okx.com/api/v5/public/funding-rate?instId={iid}", timeout=5.0)
                if res and str(res.get("code")) == "0" and res.get("data"):
                    row = res["data"][0]
                    try:
                        rec["rate"] = float(row.get("fundingRate") or 0.0)
                        ft = int(row.get("fundingTime") or 0)
                        nft = int(row.get("nextFundingTime") or 0)
                        if nft > ft > 0:
                            rec["interval_h"] = round((nft - ft) / 3600000.0, 2)
                    except (TypeError, ValueError):
                        pass
                elif err:
                    rec["error"] = err
            else:
                sid = _sym_to_binance_inst(sym)
                res, err = http_get_json(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sid}", timeout=5.0)
                if res and "lastFundingRate" in res:
                    try:
                        rec["rate"] = float(res.get("lastFundingRate") or 0.0)
                    except (TypeError, ValueError):
                        pass
                elif err:
                    rec["error"] = err
            funding_cache[ck] = rec

        finfo = funding_cache[ck]
        rate = finfo.get("rate")
        if rate is None:
            continue
        # Adverse rate: long pays positive funding, short pays negative funding
        adverse_rate = rate if side == "long" else -rate
        interval_h = float(finfo.get("interval_h") or 8.0)
        observed.append({
            "bot": bs,
            "symbol": sym,
            "side": side,
            "rate_pct": round(rate * 100.0, 4),
            "adverse_pct": round(adverse_rate * 100.0, 4),
            "interval_h": interval_h,
        })

        if adverse_rate >= 0.0012:
            alerts.append({
                "bot_id": bs,
                "key": "infra_funding_drain",
                "severity": "CRITICAL",
                "title": f"극단적 불리 펀딩비 출혈 ({sym} {side})",
                "details": f"정산 펀딩비 {rate*100:+.4f}% (불리 부담 {adverse_rate*100:.4f}% / {interval_h:.0f}h 주기)",
                "recommendation": "장기 보유 시 펀딩비로 수익 급속 잠식 — 청산 타이밍 및 헤지 검토 필요",
            })
        elif adverse_rate >= 0.0005 or (interval_h <= 4.0 and adverse_rate >= 0.0003):
            alerts.append({
                "bot_id": bs,
                "key": "infra_funding_drain",
                "severity": "WARN",
                "title": f"고율 불리 펀딩비 주의 ({sym} {side})",
                "details": f"펀딩비 {rate*100:+.4f}% (불리 {adverse_rate*100:.4f}% / {interval_h:.0f}h 주기)",
                "recommendation": "단축 정산 또는 고율 펀딩 누적 추이 관찰 권고",
            })

    return {"alerts": alerts, "details": {"positions": observed}}


def check_api_key_lifecycle_and_auth_logs(bots: List[int]) -> Dict[str, Any]:
    """[M23] Detect auth/IP failures in recent logs + optional api_key_meta.json TTL countdown."""
    alerts: List[Dict[str, str]] = []
    now_local = datetime.now()
    cutoff = now_local - timedelta(minutes=15)
    auth_hits: Dict[str, str] = {}

    for b in bots:
        bs = str(b)
        lp = os.path.join(BASE_PROJECT, bs, "bot_engine.log")
        if not os.path.exists(lp):
            continue
        try:
            with open(lp, "rb") as f:
                f.seek(0, os.SEEK_END)
                sz = f.tell()
                f.seek(max(0, sz - 65536))
                chunk = f.read().decode("utf-8", errors="ignore")
            for line in reversed(chunk.splitlines()):
                if len(line) >= 19:
                    try:
                        ldt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                        if ldt < cutoff:
                            break
                    except ValueError:
                        pass
                if _AUTH_ERR_RE.search(line):
                    auth_hits[bs] = line.strip()[:160]
                    break
        except Exception:
            pass

    for bs, sample in auth_hits.items():
        alerts.append({
            "bot_id": bs,
            "key": "infra_api_auth_error",
            "severity": "CRITICAL",
            "title": "API 인증/IP 화이트리스트 오류 감지",
            "details": sample,
            "recommendation": "즉시 거래소 API 키 만료·권한·IP 화이트리스트 상태 확인 필요",
        })

    expiry_status: Dict[str, Any] = {}
    meta = _load_json(API_KEY_META_FILE, {}) or {}
    if isinstance(meta, dict):
        today = now_local.date()
        for label, item in meta.items():
            if not isinstance(item, dict):
                continue
            exp_s = str(item.get("expires_at") or "").strip()[:10]
            try:
                exp_d = datetime.strptime(exp_s, "%Y-%m-%d").date()
            except ValueError:
                continue
            days_left = (exp_d - today).days
            bot_id = str(item.get("bot_id") or label or "8888")
            expiry_status[bot_id] = {"expires_at": exp_s, "days_left": days_left}
            if days_left <= 3:
                alerts.append({
                    "bot_id": bot_id,
                    "key": "infra_api_key_expiry",
                    "severity": "CRITICAL",
                    "title": f"API 키 만료 D-{max(0, days_left)} 임박",
                    "details": f"{label} 만료일 {exp_s} ({days_left}일 남음)",
                    "recommendation": "만료 전 신규 API 키 발급 및 .env 교체 준비 필요",
                })
            elif days_left <= 7:
                alerts.append({
                    "bot_id": bot_id,
                    "key": "infra_api_key_expiry",
                    "severity": "WARN",
                    "title": f"API 키 만료 D-{days_left} 예고",
                    "details": f"{label} 만료일 {exp_s} ({days_left}일 남음)",
                    "recommendation": "API 키 재발급 일정 계획 권고",
                })

    return {"alerts": alerts, "details": {"auth_hits": auth_hits, "expiry_status": expiry_status}}


def _parse_etime_sec(etime_str: str) -> int:
    s = str(etime_str or "").strip()
    days = 0
    if "-" in s:
        dpart, s = s.split("-", 1)
        days = int(dpart) if dpart.isdigit() else 0
    parts = [int(p) if p.isdigit() else 0 for p in s.split(":")]
    if len(parts) == 3:
        return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return days * 86400 + parts[0] * 60 + parts[1]
    return days * 86400 + (parts[0] if parts else 0)


def check_host_resources_and_rotate_logs(bots: List[int]) -> Dict[str, Any]:
    """[M24] Check disk capacity, RSS memory, FD count, stale helper scripts, and rotate 8888 logs."""
    alerts: List[Dict[str, str]] = []

    # 1) Copy-truncate safe rotation on large 8888 log files (>10MB, keep 3 backups)
    rotated: List[str] = []
    for fname in (
        "watchdog_entry.log",
        "watchdog_profitability.log",
        "watchdog_keeper.log",
        "watchdog_position.log",
        "watchdog_exit.log",
        "app.log",
        "streamlit_8888.log",
        "ledger_sync.log",
    ):
        lp = os.path.join(BASE_8888, fname)
        if rotate_log_copytruncate(lp, max_bytes=10 * 1024 * 1024, keep=3):
            rotated.append(fname)

    # 2) Disk usage check
    du = shutil.disk_usage(BASE_PROJECT)
    disk_used_pct = round((du.used / du.total) * 100.0, 1) if du.total else 0.0
    if disk_used_pct >= 92.0:
        alerts.append({
            "bot_id": "8888",
            "key": "infra_disk_full",
            "severity": "CRITICAL",
            "title": f"디스크 용량 고갈 위험 ({disk_used_pct}%)",
            "details": f"{BASE_PROJECT} 사용률 {disk_used_pct}% (여유 {du.free / (1024**3):.1f}GB)",
            "recommendation": "오래된 백업 로그(.bak) 정리 및 디스크 확보 필요",
        })
    elif disk_used_pct >= 85.0:
        alerts.append({
            "bot_id": "8888",
            "key": "infra_disk_full",
            "severity": "WARN",
            "title": f"디스크 사용률 주의 ({disk_used_pct}%)",
            "details": f"{BASE_PROJECT} 사용률 {disk_used_pct}% (여유 {du.free / (1024**3):.1f}GB)",
            "recommendation": "불필요한 백업/대용량 로그 정리 검토 권고",
        })

    # 3) Single `ps` scan for RSS memory & long-running orphan helper scripts
    high_rss: List[Tuple[str, float, int]] = []
    orphan_helpers: List[str] = []
    bot_pids: List[Tuple[str, int]] = []
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,rss,etime,command"], text=True, timeout=5)
        for line in out.splitlines()[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            pid_s, rss_s, etime_s, cmd = parts
            if not (pid_s.isdigit() and rss_s.isdigit()):
                continue
            pid = int(pid_s)
            rss_mb = round(int(rss_s) / 1024.0, 1)
            if "/Users/l/project/" not in cmd:
                continue
            # Identify bot or 8888 app processes
            matched_id = None
            for b in bots:
                if f"/{b}/bot.py" in cmd:
                    matched_id = str(b)
                    break
            if not matched_id and "/Users/l/project/8888/app.py" in cmd:
                matched_id = "8888"
            if matched_id:
                bot_pids.append((matched_id, pid))
                if rss_mb > 900.0:
                    high_rss.append((matched_id, rss_mb, pid))
                    alerts.append({
                        "bot_id": matched_id,
                        "key": "infra_memory_leak",
                        "severity": "CRITICAL",
                        "title": f"메모리 급증 ({rss_mb:.0f}MB)",
                        "details": f"PID {pid} RSS={rss_mb:.1f}MB (>900MB 임계 초과)",
                        "recommendation": "메모리 누수 의심 — 포지션/캐시 점검 및 안전 재기동 검토",
                    })
                elif rss_mb > 500.0:
                    high_rss.append((matched_id, rss_mb, pid))
                    alerts.append({
                        "bot_id": matched_id,
                        "key": "infra_memory_leak",
                        "severity": "WARN",
                        "title": f"메모리 사용 증가 ({rss_mb:.0f}MB)",
                        "details": f"PID {pid} RSS={rss_mb:.1f}MB (>500MB 주의)",
                        "recommendation": "메모리 증가 추이 주시",
                    })
            elif "/Users/l/project/8888/lab/" in cmd or "/tmp/test_" in cmd:
                esec = _parse_etime_sec(etime_s)
                if esec >= 600:
                    orphan_helpers.append(f"PID {pid} ({etime_s}, {cmd.split()[-1]})")
    except Exception:
        pass

    if orphan_helpers:
        alerts.append({
            "bot_id": "8888",
            "key": "infra_orphan_helpers",
            "severity": "WARN",
            "title": f"장기 상주 보조 스크립트 감지 ({len(orphan_helpers)}건)",
            "details": " | ".join(orphan_helpers[:4]),
            "recommendation": "백테스트/일회성 리포트 프로세스 잔류 여부 확인 권고",
        })

    # 4) Open FD check on monitored bot processes via lsof (single batched call)
    high_fds: Dict[str, int] = {}
    if bot_pids:
        try:
            pid_csv = ",".join(str(pid) for _, pid in bot_pids)
            pid_to_id = {str(pid): bid for bid, pid in bot_pids}
            out = subprocess.check_output(["lsof", "-n", "-P", "-F", "p", "-p", pid_csv], text=True, timeout=4, stderr=subprocess.DEVNULL)
            cur_pid = None
            counts: Dict[str, int] = {}
            for line in out.splitlines():
                if line.startswith("p"):
                    cur_pid = line[1:].strip()
                elif line.startswith("f") and cur_pid:
                    counts[cur_pid] = counts.get(cur_pid, 0) + 1
            for p_s, cnt in counts.items():
                if cnt > 1024:
                    bid = pid_to_id.get(p_s, "8888")
                    high_fds[bid] = cnt
                    alerts.append({
                        "bot_id": bid,
                        "key": "infra_fd_leak",
                        "severity": "WARN",
                        "title": f"열린 파일디스크립터 과다 ({cnt}개)",
                        "details": f"PID {p_s} open FD={cnt} (>1024)",
                        "recommendation": "소켓/로그 파일 누수 여부 점검 권고",
                    })
        except Exception:
            pass

    return {
        "alerts": alerts,
        "details": {
            "disk_used_pct": disk_used_pct,
            "rotated_logs": rotated,
            "high_rss": high_rss,
            "orphan_helpers": orphan_helpers,
            "high_fds": high_fds,
        },
    }


def run_exchange_infra_audit(bots: List[int], include_listings: bool = False) -> Dict[str, Any]:
    """Run M17/M18/M20/M23/M24 checks, persist data/infra_health.json, and return unified alert list."""
    m17 = check_exchange_maintenance_and_listings(bots, include_listings=include_listings)
    m18 = check_clock_drift_and_latency(bots)
    m20 = check_funding_rates_for_positions(bots)
    m23 = check_api_key_lifecycle_and_auth_logs(bots)
    m24 = check_host_resources_and_rotate_logs(bots)

    all_alerts = (
        m17["alerts"] + m18["alerts"] + m20["alerts"] + m23["alerts"] + m24["alerts"]
    )

    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "include_listings": include_listings,
        "m17_maintenance_listings": m17["details"],
        "m18_clock_latency_429": m18["details"],
        "m20_funding_rates": m20["details"],
        "m23_api_auth_lifecycle": m23["details"],
        "m24_host_resources": m24["details"],
        "alert_count": len(all_alerts),
    }
    try:
        _atomic_write_json(INFRA_HEALTH_FILE, payload)
    except Exception:
        pass

    return {"alerts": all_alerts, "summary": payload}
