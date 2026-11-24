#!/usr/bin/env python3
"""
bot_sentinel.py — 봇 체결 장부, 포지션 보호정밀도, 청산거리 & 마켓 위생 상시 감사탑 (Aegis V6)
1. 유령(Ghost) / 고아(Orphan) 포지션 탐지 및 로컬 active_positions 동기화
2. [M15] 거래소 실포지션 청산거리(Liq Distance)·유지마진비율·마진모드·보호주문 수량/방향/청산가 바깥 배치 정밀 대조
3. [결함 수정] 보호주문 조회 API 실패 시 Fail-Open(True 은폐) 차단 + OKX 무포지션 고아 알고주문(OCO/Cond) 감지
4. [M21] 장기 방치 미체결 지정가 주문(>10m) & 먼지 잔고(Dust) 탐지
5. [M23] API 인증/IP/권한 오류(-2015, 50111, 50113 등) 전용 플래그 반환
6. [M16/M20 지원] 실시간 계좌/포지션 스냅샷 data/sentinel_live_cache.json 원자적 기록
7. 잔고 괴리율(Ledger Drift) 및 stats.json 전적 장부 무결성 동기화
"""
import asyncio
import csv
import fcntl
import json
import os
import sys
import tempfile
import time
from datetime import datetime

SENTINEL_LIVE_CACHE = "/Users/l/project/8888/data/sentinel_live_cache.json"
SENTINEL_LIVE_LOCK = "/tmp/watchdog_sentinel_live_cache.lock"
_AUTH_KEYWORDS = ("-2015", "50111", "50113", "invalid api-key", "api-key", "401", "403", "permission", "ip")


def atomic_write_json(filepath, data):
    dir_name = os.path.dirname(filepath)
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=2, ensure_ascii=False)
        temp_name = tf.name
    os.replace(temp_name, filepath)


def atomic_append_csv(filepath, new_rows, fieldnames=None):
    if not new_rows:
        return 0
    existing = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not fieldnames:
                fieldnames = list(reader.fieldnames or [])
            existing = list(reader)

    if not fieldnames:
        fieldnames = ["시간", "심볼", "유형", "방향", "가격", "수량", "수익(USDT)", "수익률(%)", "청산유형", "레버리지", "주문ID", "체결ID", "수수료(USDT)", "매매모드"]

    existing_tids = set()
    for r in existing:
        tid = r.get("체결ID") or r.get("trade_id") or ""
        for sub in str(tid).split("|"):
            if sub:
                existing_tids.add(sub)

    added = 0
    for nr in new_rows:
        nr_tid = nr.get("체결ID") or nr.get("trade_id") or ""
        is_dup = False
        for sub in str(nr_tid).split("|"):
            if sub and sub in existing_tids:
                is_dup = True
                break
        if not is_dup:
            existing.append(nr)
            added += 1
            if nr_tid:
                for sub in str(nr_tid).split("|"):
                    if sub:
                        existing_tids.add(sub)

    if added > 0:
        existing.sort(key=lambda x: x.get("시간") or x.get("timestamp") or "")
        dir_name = os.path.dirname(filepath)
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8", newline="") as tf:
            writer = csv.DictWriter(tf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing)
            temp_name = tf.name
        os.replace(temp_name, filepath)
    return added


def _update_sentinel_live_cache(bot_id: int, payload: dict) -> None:
    os.makedirs(os.path.dirname(SENTINEL_LIVE_CACHE), exist_ok=True)
    with open(SENTINEL_LIVE_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = {"bots": {}, "updated": ""}
            if os.path.exists(SENTINEL_LIVE_CACHE):
                try:
                    with open(SENTINEL_LIVE_CACHE, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            doc = loaded
                except Exception:
                    pass
            doc.setdefault("bots", {})[str(bot_id)] = payload
            doc["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            atomic_write_json(SENTINEL_LIVE_CACHE, doc)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _safe_float(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_auth_err(err_text: str) -> bool:
    low = str(err_text or "").lower()
    return any(k in low for k in _AUTH_KEYWORDS)


async def audit_bot(b: int):
    cwd = f"/Users/l/project/{b}"
    if not os.path.exists(cwd):
        return {"error": "CWD_NOT_FOUND"}

    sys.path.insert(0, cwd)
    cfg_file = os.path.join(cwd, "config.json")
    ex_id = "binance"
    expected_margin_mode = "isolated"
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
            ex_id = str(cfg_json.get("EXCHANGE_ID", "binance")).lower()
            expected_margin_mode = str(cfg_json.get("MARGIN_MODE", "isolated") or "isolated").lower()
        except Exception:
            pass

    from core.api_keys import load_api_keys
    load_api_keys(override=True)

    client = None
    try:
        if ex_id == "okx":
            from core.exchange import OKXClient
            client = OKXClient(os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET_KEY"), os.getenv("OKX_PASSPHRASE"))
        else:
            from core.exchange import BinanceClient
            client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))
        await client.load_markets()
    except Exception as e:
        err_s = str(e)
        return {
            "error": f"CLIENT_INIT_FAILED: {err_s}",
            "auth_error": err_s[:180] if _is_auth_err(err_s) else "",
        }

    report = {
        "bot": b,
        "exchange": ex_id,
        "ghosts_cleaned": [],
        "orphans_restored": [],
        "unprotected_positions": [],
        "protection_check_errors": [],
        "protection_mismatches": [],
        "liq_warnings": [],
        "margin_mode_warnings": [],
        "orphan_algo_orders": [],
        "stale_open_orders": [],
        "dust_positions": [],
        "auth_error": "",
        "partial_exits_added": 0,
        "balance_diff": 0.0,
        "actions": [],
    }

    try:
        bal = await client.get_balance()
        positions = await client.get_positions()
        try:
            raw_positions = await client._execute_with_retry(client.exchange.fetch_positions)
        except Exception:
            raw_positions = []

        ex_map = {}
        for p in positions:
            cnt = abs(_safe_float(p.get("contracts") or p.get("amount") or p.get("size"), 0.0))
            if cnt > 0:
                ex_map[p["symbol"]] = p

        # Build raw position risk map (liquidation price, margin mode, mgnRatio/marginRatio, notional)
        raw_risk_map = {}
        for rp in (raw_positions or []):
            amt = abs(_safe_float(rp.get("contracts") or rp.get("amount") or (rp.get("info") or {}).get("positionAmt"), 0.0))
            if amt <= 0:
                continue
            rsym = str(rp.get("symbol") or "")
            info = rp.get("info") or {}
            mark_px = _safe_float(rp.get("markPrice") or info.get("markPx") or rp.get("lastPrice"), 0.0)
            liq_px = _safe_float(rp.get("liquidationPrice") or info.get("liqPx"), 0.0)
            entry_px = _safe_float(rp.get("entryPrice") or info.get("avgPx"), 0.0)
            notional = abs(_safe_float(rp.get("notional") or info.get("notionalUsd"), 0.0))
            if notional <= 0 and rsym in ex_map:
                notional = abs(_safe_float(ex_map[rsym].get("coins") or amt, 0.0)) * (mark_px or entry_px)
            mmode = str(rp.get("marginMode") or info.get("mgnMode") or "").lower()
            raw_risk_map[rsym] = {
                "symbol": rsym,
                "side": str(rp.get("side") or ex_map.get(rsym, {}).get("side") or "").lower(),
                "contracts": amt,
                "entry_price": entry_px or _safe_float(ex_map.get(rsym, {}).get("entry_price"), 0.0),
                "mark_price": mark_px or _safe_float(ex_map.get(rsym, {}).get("mark_price"), 0.0),
                "liq_price": liq_px,
                "notional_usdt": round(notional, 4),
                "margin_usdt": round(_safe_float(ex_map.get(rsym, {}).get("margin") or rp.get("initialMargin"), 0.0), 4),
                "margin_mode": mmode,
                "okx_mgn_ratio": _safe_float(info.get("mgnRatio"), 0.0),
                "bnc_margin_ratio": _safe_float(rp.get("marginRatio"), 0.0),
                "unrealized_pnl": round(_safe_float(rp.get("unrealizedPnl") or ex_map.get(rsym, {}).get("pnl_usdt"), 0.0), 4),
            }

        act_file = os.path.join(cwd, "data", "active_positions.json")
        csv_file = os.path.join(cwd, "data", "trade_history.csv")

        local_act = {}
        if os.path.exists(act_file):
            try:
                with open(act_file, "r", encoding="utf-8") as f:
                    local_act = json.load(f)
            except Exception:
                pass

        # 1. 거래소 체결 대사 및 누락 체결 자동 복원 (Reconciliation)
        try:
            from core.engine import QuantumEngine
            eng = QuantumEngine.get_instance()
            eng.client = client
            if hasattr(eng, "pnl_reconciler") and eng.pnl_reconciler:
                sync_res = await eng.pnl_reconciler.sync_trades_async()
                if sync_res and sync_res > 0:
                    report["actions"].append(f"누락 체결 {sync_res}건 자동 복원")
        except Exception:
            pass

        # 2. 유령 포지션 감시 (Ghost: 로컬엔 있는데 거래소엔 없음)
        ghosts = set(local_act.keys()) - set(ex_map.keys())
        if ghosts:
            for g in ghosts:
                report["ghosts_cleaned"].append(g)
                local_act.pop(g, None)
            atomic_write_json(act_file, local_act)
            report["actions"].append(f"유령 포지션 {len(ghosts)}건 정리")

        # 3. 고아 포지션 감시 (Orphan: 거래소엔 있는데 로컬엔 없음)
        orphans = set(ex_map.keys()) - set(local_act.keys())
        if orphans:
            for o in orphans:
                local_act[o] = {
                    "strategy_type": "DualBB" if ex_id == "binance" else "Breakout",
                    "atr_activation": 0.015,
                    "atr_callback": 0.008,
                    "exit_profile": "SL/TP",
                    "open_time": datetime.now().isoformat(),
                }
                report["orphans_restored"].append(o)
            atomic_write_json(act_file, local_act)
            report["actions"].append(f"고아 포지션 {len(orphans)}건 복원")

        # 3.5. [M15 + 결함#1/#2 수정] 보호주문(개수/수량/방향/청산가 내측 배치), 청산거리, 마진모드, 고아 알고주문, 미체결, Dust 대조
        now_ms = time.time() * 1000.0
        try:
            if ex_id == "binance":
                client.exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
            open_orders = await client._execute_with_retry(client.exchange.fetch_open_orders)
        except Exception as oo_err:
            if _is_auth_err(str(oo_err)):
                report["auth_error"] = str(oo_err)[:180]
            open_orders = []

        # M21: Stale non-conditional limit orders (>10m)
        for oo in (open_orders or []):
            otype = str(oo.get("type") or (oo.get("info") or {}).get("origType") or "").upper()
            if "STOP" in otype or "TAKE_PROFIT" in otype:
                continue
            ots = _safe_float(oo.get("timestamp") or (oo.get("info") or {}).get("time"), 0.0)
            if ots > 0 and (now_ms - ots) > 600_000:
                age_m = round((now_ms - ots) / 60_000.0, 1)
                report["stale_open_orders"].append({
                    "symbol": oo.get("symbol"),
                    "id": oo.get("id"),
                    "side": oo.get("side"),
                    "age_min": age_m,
                })

        # Fetch pending algo orders across subaccount
        okx_pending_algos = []
        okx_algo_err = None
        bnc_pending_algos = []
        bnc_algo_err = None
        if ex_id == "okx":
            try:
                res_oco = await client._execute_with_retry(
                    client.exchange.privateGetTradeOrdersAlgoPending,
                    {"instType": "SWAP", "ordType": "oco"},
                )
                res_cond = await client._execute_with_retry(
                    client.exchange.privateGetTradeOrdersAlgoPending,
                    {"instType": "SWAP", "ordType": "conditional"},
                )
                okx_pending_algos = list((res_oco or {}).get("data") or []) + list((res_cond or {}).get("data") or [])
            except Exception as oe:
                okx_algo_err = str(oe)
                if _is_auth_err(okx_algo_err):
                    report["auth_error"] = okx_algo_err[:180]
        elif ex_id == "binance" and hasattr(client, "_fetch_algo_orders"):
            try:
                bnc_pending_algos = list(await client._fetch_algo_orders() or [])
            except Exception as be:
                bnc_algo_err = str(be)
                if _is_auth_err(bnc_algo_err):
                    report["auth_error"] = bnc_algo_err[:180]

        if ex_map:
            now_dt = datetime.now()
            for sym, pinfo in ex_map.items():
                rinfo = raw_risk_map.get(sym, {})
                contracts = abs(_safe_float(rinfo.get("contracts") or pinfo.get("size"), 0.0))
                side = str(rinfo.get("side") or pinfo.get("side") or "").lower()
                mark_px = _safe_float(rinfo.get("mark_price") or pinfo.get("mark_price"), 0.0)
                liq_px = _safe_float(rinfo.get("liq_price"), 0.0)
                notional = _safe_float(rinfo.get("notional_usdt"), 0.0)
                mmode = str(rinfo.get("margin_mode") or "").lower()

                # M21: Dust check
                if 0 < notional < 1.0:
                    report["dust_positions"].append({"symbol": sym, "notional_usdt": notional})

                # M15: Margin mode drift check
                if mmode and expected_margin_mode and mmode != expected_margin_mode:
                    report["margin_mode_warnings"].append({
                        "symbol": sym,
                        "expected": expected_margin_mode,
                        "actual": mmode,
                    })

                # M15: Liquidation distance & Maintenance margin ratio check
                liq_dist_pct = None
                if mark_px > 0 and liq_px > 0:
                    liq_dist_pct = round((abs(mark_px - liq_px) / mark_px) * 100.0, 2)
                    rinfo["liq_dist_pct"] = liq_dist_pct
                    if liq_dist_pct < 8.0:
                        report["liq_warnings"].append({
                            "symbol": sym, "severity": "CRITICAL",
                            "liq_dist_pct": liq_dist_pct, "mark": mark_px, "liq": liq_px,
                        })
                    elif liq_dist_pct < 15.0:
                        report["liq_warnings"].append({
                            "symbol": sym, "severity": "WARN",
                            "liq_dist_pct": liq_dist_pct, "mark": mark_px, "liq": liq_px,
                        })

                if ex_id == "okx":
                    mr = _safe_float(rinfo.get("okx_mgn_ratio"), 0.0)
                    if 0 < mr < 1.3:
                        report["liq_warnings"].append({"symbol": sym, "severity": "CRITICAL", "okx_mgn_ratio": mr})
                    elif 0 < mr < 1.8:
                        report["liq_warnings"].append({"symbol": sym, "severity": "WARN", "okx_mgn_ratio": mr})
                elif ex_id == "binance":
                    bmr = _safe_float(rinfo.get("bnc_margin_ratio"), 0.0)
                    if bmr >= 0.75:
                        report["liq_warnings"].append({"symbol": sym, "severity": "CRITICAL", "bnc_margin_ratio": bmr})
                    elif bmr >= 0.55:
                        report["liq_warnings"].append({"symbol": sym, "severity": "WARN", "bnc_margin_ratio": bmr})

                # 90s grace right after entry
                ot_str = (local_act.get(sym) or {}).get("open_time")
                in_entry_grace = False
                if ot_str:
                    try:
                        ot_dt = datetime.fromisoformat(str(ot_str).split(".")[0].split("+")[0])
                        if abs((now_dt - ot_dt).total_seconds()) < 90:
                            in_entry_grace = True
                    except Exception:
                        pass
                if in_entry_grace:
                    continue

                # Protection order presence & exact qty/direction/liq consistency check
                if ex_id == "okx":
                    if okx_algo_err:
                        report["protection_check_errors"].append({"symbol": sym, "error": okx_algo_err[:120]})
                        continue
                    try:
                        inst_id = client.exchange.market(sym).get("id")
                    except Exception:
                        inst_id = None
                    sym_algos = [a for a in okx_pending_algos if inst_id and a.get("instId") == inst_id]
                    if not sym_algos:
                        report["unprotected_positions"].append(sym)
                    else:
                        sl_qty = 0.0
                        for a in sym_algos:
                            pside = str(a.get("posSide") or "").lower()
                            if pside in ("long", "short") and side and pside != side:
                                report["protection_mismatches"].append(f"{sym}: posSide 불일치(algo={pside}, pos={side})")
                            sl_px = _safe_float(a.get("slTriggerPx") or a.get("triggerPx"), 0.0)
                            if sl_px > 0:
                                sl_qty += _safe_float(a.get("sz"), 0.0)
                                if liq_px > 0:
                                    if side == "long" and sl_px <= liq_px * 0.999:
                                        report["protection_mismatches"].append(f"{sym}: 롱 SL({sl_px}) <= 청산가({liq_px})")
                                    elif side == "short" and sl_px >= liq_px * 1.001:
                                        report["protection_mismatches"].append(f"{sym}: 숏 SL({sl_px}) >= 청산가({liq_px})")
                        if contracts > 0 and 0 < sl_qty < contracts * 0.95:
                            report["protection_mismatches"].append(f"{sym}: SL수량({sl_qty}) < 포지션({contracts})")

                else:  # binance
                    if bnc_algo_err:
                        report["protection_check_errors"].append({"symbol": sym, "error": bnc_algo_err[:120]})
                        continue
                    try:
                        mkt_id = client.exchange.market(sym).get("id")
                    except Exception:
                        mkt_id = sym.split(":")[0].replace("/", "")
                    sl_orders = []
                    tp_orders = []
                    for a in bnc_pending_algos:
                        if a.get("symbol") != mkt_id:
                            continue
                        ot = str(a.get("orderType") or "").upper()
                        if "STOP" in ot and "TAKE_PROFIT" not in ot:
                            sl_orders.append(a)
                        elif "TAKE_PROFIT" in ot:
                            tp_orders.append(a)
                    for o in (open_orders or []):
                        if o.get("symbol") != sym:
                            continue
                        ot = str(o.get("type") or (o.get("info") or {}).get("origType") or "").upper()
                        if "STOP" in ot and "TAKE_PROFIT" not in ot:
                            sl_orders.append(o)
                        elif "TAKE_PROFIT" in ot:
                            tp_orders.append(o)

                    if not sl_orders and not tp_orders:
                        # Double check via client helper if available, without assuming True on failure
                        try:
                            has_prot = bool(await client.has_protective_orders(sym)) if hasattr(client, "has_protective_orders") else False
                        except Exception as hp_err:
                            report["protection_check_errors"].append({"symbol": sym, "error": str(hp_err)[:120]})
                            has_prot = None
                        if has_prot is False:
                            report["unprotected_positions"].append(sym)
                    elif not sl_orders:
                        report["protection_mismatches"].append(f"{sym}: TP만 존재하고 SL 손절주문 누락")
                    else:
                        covered_full = any(bool(x.get("closePosition") or (x.get("info") or {}).get("closePosition")) for x in sl_orders)
                        sl_qty = sum(_safe_float(x.get("quantity") or x.get("amount"), 0.0) for x in sl_orders)
                        if not covered_full and contracts > 0 and sl_qty < contracts * 0.95:
                            report["protection_mismatches"].append(f"{sym}: SL수량({sl_qty}) < 포지션({contracts})")
                        for x in sl_orders:
                            pside = str(x.get("positionSide") or (x.get("info") or {}).get("positionSide") or "").lower()
                            if pside in ("long", "short") and side and pside != side:
                                report["protection_mismatches"].append(f"{sym}: posSide 불일치(algo={pside}, pos={side})")
                            spx = _safe_float(x.get("triggerPrice") or x.get("stopPrice"), 0.0)
                            if spx > 0 and liq_px > 0:
                                if side == "long" and spx <= liq_px * 0.999:
                                    report["protection_mismatches"].append(f"{sym}: 롱 SL({spx}) <= 청산가({liq_px})")
                                elif side == "short" and spx >= liq_px * 1.001:
                                    report["protection_mismatches"].append(f"{sym}: 숏 SL({spx}) >= 청산가({liq_px})")

            if report["unprotected_positions"]:
                report["actions"].append(f"보호주문(SL/TP) 누락 감지: {', '.join(report['unprotected_positions'])}")
            if report["protection_mismatches"]:
                report["actions"].append(f"보호주문 정합 이상: {', '.join(report['protection_mismatches'])}")
            if report["protection_check_errors"]:
                report["actions"].append(f"보호주문 조회 실패 {len(report['protection_check_errors'])}건")

            # 보유 포지션 컨텍스트 누락 방어 보정
            ctx_changed = False
            for sym in ex_map:
                ent = local_act.get(sym)
                if isinstance(ent, dict):
                    if not ent.get("exit_profile"):
                        ent["exit_profile"] = "SL/TP"
                        ctx_changed = True
                    if _safe_float(ent.get("atr_activation"), 0.0) <= 0:
                        ent["atr_activation"] = 0.015
                        ctx_changed = True
                    if _safe_float(ent.get("atr_callback"), 0.0) <= 0:
                        ent["atr_callback"] = 0.008
                        ctx_changed = True
            if ctx_changed:
                atomic_write_json(act_file, local_act)
                report["actions"].append("포지션 트레일링 컨텍스트 보정")
        else:
            # Flat: check orphan algo orders cleanly
            if ex_id == "okx" and okx_pending_algos:
                for a in okx_pending_algos:
                    report["orphan_algo_orders"].append({
                        "instId": a.get("instId"),
                        "algoId": a.get("algoId"),
                        "ordType": a.get("ordType"),
                    })
                report["actions"].append(f"OKX 무포지션 고아 알고주문 {len(okx_pending_algos)}건 감지")
            elif ex_id == "binance" and hasattr(client, "sweep_orphan_algo"):
                try:
                    swept = await client.sweep_orphan_algo([])
                    if swept and swept > 0:
                        report["actions"].append(f"무포지션 고아 알고주문 {swept}건 자동 청소")
                except Exception:
                    pass

        # 4. 잔고 괴리율 검사 (Ledger Drift Guard)
        seed_money = 10.0
        perf_start = "2026-09-01 00:00:00"
        seeds_file = "/Users/l/project/8888/seeds.json"
        if os.path.exists(seeds_file):
            try:
                with open(seeds_file, "r", encoding="utf-8") as sf:
                    binfo = json.load(sf).get(str(b), {})
                    seed_money = float(binfo.get("seed", 10.0))
                    perf_start = binfo.get("perf_start", "2026-09-01 00:00:00")
            except Exception:
                pass

        total_bal = _safe_float(bal.get("total"), 0.0)
        u_pnl = _safe_float(bal.get("pnl"), 0.0)

        local_trades = []
        if os.path.exists(csv_file):
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    t_str = r.get("시간") or r.get("timestamp", "")
                    if t_str >= perf_start:
                        local_trades.append(r)

        exits = [t for t in local_trades if t.get("유형") in ("청산", "청산(로테이션)") or t.get("category") == "청산"]
        gross_pnl = sum(_safe_float(t.get("수익(USDT)") or t.get("pnl"), 0.0) for t in exits)
        fees = sum(_safe_float(t.get("수수료(USDT)") or t.get("fee"), 0.0) for t in local_trades)
        net_pnl = gross_pnl - fees
        theo_bal = seed_money + net_pnl + u_pnl

        drift = round(total_bal - theo_bal, 4)
        report["balance_diff"] = drift
        if abs(drift) > 0.10 and len(ex_map) == 0:
            report["actions"].append(f"잔고 괴리 감지 (${drift:+.4f})")

        # Persist real-time live cache for M16/M20/M21 portfolio & funding checks
        try:
            _update_sentinel_live_cache(
                b,
                {
                    "ts": time.time(),
                    "ts_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "exchange": ex_id,
                    "balance": round(total_bal, 4),
                    "u_pnl": round(u_pnl, 4),
                    "positions": list(raw_risk_map.values()),
                    "stale_open_orders": report["stale_open_orders"],
                    "dust_positions": report["dust_positions"],
                    "orphan_algo_orders": report["orphan_algo_orders"],
                },
            )
        except Exception:
            pass

        # 5. stats.json 전적 동기화 감사 (Stats Ledger Reconciliation Guard)
        stats_file = os.path.join(cwd, "data", "stats.json")
        if os.path.exists(stats_file) and os.path.exists(csv_file):
            try:
                with open(stats_file, "r", encoding="utf-8") as sf:
                    st_data = json.load(sf)
                st_perf = st_data.get("perf_start_time") or perf_start
                with open(csv_file, "r", encoding="utf-8-sig") as cf:
                    all_rows = list(csv.DictReader(cf))

                entry_order_ids = {
                    str(r.get("주문ID") or r.get("order_id") or "").strip()
                    for r in all_rows
                    if str(r.get("유형") or r.get("category") or "").strip() in ("진입", "*진입")
                    and str(r.get("주문ID") or r.get("order_id") or "").strip()
                }

                order_pnls = {}
                for idx, r in enumerate(all_rows):
                    t_str = str(r.get("시간") or r.get("timestamp", ""))[:19].replace("T", " ")
                    cat = str(r.get("유형") or r.get("category") or "").strip()
                    if t_str < st_perf:
                        continue
                    if cat not in ("청산", "청산(로테이션)") and str(r.get("side", "")).lower() != "exit":
                        continue
                    pnl = _safe_float(r.get("수익(USDT)") or r.get("pnl"), 0.0)
                    oid = str(r.get("주문ID") or r.get("order_id") or "").strip()
                    if oid and oid in entry_order_ids and abs(pnl) <= 1e-12:
                        continue
                    key = oid if oid else f"_uniq_{idx}"
                    order_pnls[key] = order_pnls.get(key, 0.0) + pnl

                real_w = sum(1 for p in order_pnls.values() if p > 1e-12)
                real_l = sum(1 for p in order_pnls.values() if p < -1e-12)
                real_trades = real_w + real_l

                cur_w = st_data.get("total_wins", 0)
                cur_l = st_data.get("total_losses", 0)
                cur_trades = st_data.get("total_trades", 0)

                if (cur_w != real_w or cur_l != real_l or cur_trades != real_trades) and real_trades > 0:
                    st_data["total_wins"] = real_w
                    st_data["total_losses"] = real_l
                    st_data["total_trades"] = real_trades
                    st_data["total_pnl_usdt"] = round(sum(order_pnls.values()), 4)
                    atomic_write_json(stats_file, st_data)
                    report["actions"].append(f"전적 장부 동기화({cur_w}W/{cur_l}L→{real_w}W/{real_l}L)")
            except Exception:
                pass

    finally:
        await client.close()

    return report


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "NO_BOT_SPECIFIED"}))
        return
    b = int(sys.argv[1])
    res = asyncio.run(audit_bot(b))
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
