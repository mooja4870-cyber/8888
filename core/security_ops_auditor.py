#!/usr/bin/env python3
"""
8888 — Black-Swan, Security, Market-Feed Freeze & Mac 24/7 Ops Auditor (`core/security_ops_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers Aegis V7 modules (Read-Only monitoring + alert + daily backup, NEVER mutates bot configs):
  - M28: USDT Stablecoin Depeg cross-venue check (Binance + OKX USDC/USDT)
  - M29-env: .env secret file permissions audit (writable=CRITICAL, world-readable=INFO)
  - M32: Frozen / Stale scan_results.json Market Feed detection
  - M33: Local Mac 24/7 Ops — External Internet Outage Shield (prevents mass false restarts),
         Public IP change alert (exchange whitelist break), AC Sleep setting audit
  - M34: Telegram/Discord Canary liveness check (no message spam), CSV/JSON truncation &
         corruption detection, and automated 14-day Daily Ledger/Config Backup
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    _load_discord_webhook,
    _load_proactive_discord_webhook,
    _load_telegram_creds,
    http_get_json,
    set_external_network_down,
)

SECURITY_OPS_HEALTH_FILE = os.path.join(BASE_8888, "data", "security_ops_health.json")
FEED_FREEZE_STATE_FILE = os.path.join(BASE_8888, "data", "feed_freeze_state.json")
HOST_OPS_STATE_FILE = os.path.join(BASE_8888, "data", "host_ops_state.json")
LEDGER_INTEGRITY_FILE = os.path.join(BASE_8888, "data", "ledger_integrity_state.json")
BACKUP_ROOT = os.path.join(BASE_8888, "backups")

_IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]{6,}$")


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


def check_usdt_depeg() -> Dict[str, Any]:
    """[M28] Cross-check USDT/USD peg via USDC/USDT spot tickers on Binance & OKX."""
    alerts: List[Dict[str, str]] = []
    quotes: Dict[str, float] = {}

    bnc_res, _ = http_get_json("https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT", timeout=5.0)
    if isinstance(bnc_res, dict) and bnc_res.get("price"):
        try:
            px = float(bnc_res["price"])
            if px > 0:
                quotes["binance"] = round(1.0 / px, 5)
        except (TypeError, ValueError):
            pass

    okx_res, _ = http_get_json("https://www.okx.com/api/v5/market/ticker?instId=USDC-USDT", timeout=5.0)
    if isinstance(okx_res, dict) and str(okx_res.get("code")) == "0" and okx_res.get("data"):
        try:
            px = float((okx_res["data"][0] or {}).get("last") or 0.0)
            if px > 0:
                quotes["okx"] = round(1.0 / px, 5)
        except (TypeError, ValueError):
            pass

    usdt_usd = round(sum(quotes.values()) / len(quotes), 5) if quotes else None
    max_dev = max((abs(v - 1.0) for v in quotes.values()), default=0.0)
    avg_dev = abs(usdt_usd - 1.0) if usdt_usd is not None else 0.0

    # Require average deviation across available sources to prevent single-venue glitch noise
    if quotes and avg_dev >= 0.015:
        alerts.append({
            "bot_id": "8888",
            "key": "blackswan_usdt_depeg",
            "severity": "CRITICAL",
            "title": f"USDT 디페깅 위험 (추정가 ${usdt_usd:.4f})",
            "details": f"거래소별 추정 USDT: {quotes} (이탈 {avg_dev*100:.2f}%)",
            "recommendation": "전체 USDT 증거금 가치 변동 위험 — 포지션 노출 축소 또는 헤지 즉시 검토 필요",
        })
    elif quotes and avg_dev >= 0.005:
        alerts.append({
            "bot_id": "8888",
            "key": "blackswan_usdt_depeg",
            "severity": "WARN",
            "title": f"USDT 페그 이탈 주의 (${usdt_usd:.4f})",
            "details": f"거래소별 추정 USDT: {quotes} (이탈 {avg_dev*100:.2f}%)",
            "recommendation": "스테이블코인 환율 변동 추이 집중 관찰 권고",
        })

    return {
        "alerts": alerts,
        "details": {"usdt_usd_avg": usdt_usd, "sources": quotes, "max_dev_pct": round(max_dev * 100, 3)},
    }


def check_env_file_security(bots: List[int]) -> Dict[str, Any]:
    """[M29-env] Audit .env permissions without modifying files."""
    alerts: List[Dict[str, str]] = []
    report: Dict[str, str] = {}
    targets = [(str(b), os.path.join(BASE_PROJECT, str(b), ".env")) for b in bots]
    targets.append(("8888", os.path.join(BASE_8888, ".env")))

    for bid, path in targets:
        if not os.path.exists(path):
            continue
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            oct_s = oct(mode)[2:]
            report[bid] = oct_s
            if mode & 0o022:
                alerts.append({
                    "bot_id": bid,
                    "key": "security_env_writable",
                    "severity": "CRITICAL",
                    "title": f".env API 키 파일 쓰기권한 노출 ({oct_s})",
                    "details": f"{path} permission={oct_s} — 타 계정 수정 가능 상태",
                    "recommendation": f"chmod 600 {path} 적용 권고",
                })
            elif mode & 0o044:
                # Informational hygiene warning only (INFO level never spams Telegram/Discord)
                alerts.append({
                    "bot_id": bid,
                    "key": "security_env_readable",
                    "severity": "INFO",
                    "title": f".env 읽기권한 완화 상태 ({oct_s})",
                    "details": f"{path} permission={oct_s} (권장 600)",
                    "recommendation": f"보안 강화 시 chmod 600 {path} 권장",
                })
        except Exception:
            pass

    return {"alerts": alerts, "details": report}


def check_frozen_market_feeds(bots: List[int]) -> Dict[str, Any]:
    """[M32] Detect stale scan_results.json or frozen identical price vectors across >=3 scans."""
    alerts: List[Dict[str, str]] = []
    state = _load_json(FEED_FREEZE_STATE_FILE, {}) or {}
    new_state: Dict[str, Dict[str, Any]] = {}
    summary: Dict[str, Any] = {}
    now = time.time()

    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if not os.path.isdir(bdir) or os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        sr_path = os.path.join(bdir, "scan_results.json")
        if not os.path.exists(sr_path):
            continue

        try:
            mt = os.path.getmtime(sr_path)
            age_sec = round(now - mt, 1)
            doc = _load_json(sr_path, {})
            if not isinstance(doc, dict):
                continue
            scan_ts = str(doc.get("last_scan_time") or "")
            results = doc.get("results") or []
            if scan_ts:
                try:
                    sdt = datetime.fromisoformat(scan_ts[:26])
                    age_sec = round(max(0.0, (datetime.now() - sdt).total_seconds()), 1)
                except ValueError:
                    pass

            if age_sec >= 1800:
                alerts.append({
                    "bot_id": bs,
                    "key": "feed_stale_scan",
                    "severity": "CRITICAL",
                    "title": f"스캔 데이터 갱신 중단 ({int(age_sec//60)}분 정체)",
                    "details": f"last_scan_time={scan_ts or '?'} ({age_sec:.0f}초 경과)",
                    "recommendation": "스캐너 정지/교착 여부 즉시 확인 필요",
                })
            elif age_sec >= 600:
                alerts.append({
                    "bot_id": bs,
                    "key": "feed_stale_scan",
                    "severity": "WARN",
                    "title": f"스캔 데이터 갱신 지연 ({int(age_sec//60)}분)",
                    "details": f"last_scan_time={scan_ts or '?'} ({age_sec:.0f}초 경과)",
                    "recommendation": "스캐너 지연 추이 관찰 권고",
                })

            pairs = sorted(
                (str(r.get("symbol") or ""), round(float(r.get("price") or 0.0), 8))
                for r in results
                if isinstance(r, dict) and r.get("symbol") and float(r.get("price") or 0.0) > 0
            )
            vec_hash = hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()[:16] if pairs else ""
            prev = state.get(bs) or {}
            same_cnt = int(prev.get("same_cnt") or 0)
            if len(pairs) >= 10 and vec_hash:
                if prev.get("scan_ts") and scan_ts and scan_ts != prev.get("scan_ts"):
                    same_cnt = (same_cnt + 1) if vec_hash == prev.get("hash") else 0
                elif prev.get("hash") and vec_hash != prev.get("hash"):
                    same_cnt = 0
            else:
                same_cnt = 0

            new_state[bs] = {"scan_ts": scan_ts, "hash": vec_hash, "same_cnt": same_cnt, "pairs": len(pairs)}
            summary[bs] = {"age_sec": age_sec, "pairs": len(pairs), "frozen_streak": same_cnt}

            if same_cnt >= 3:
                alerts.append({
                    "bot_id": bs,
                    "key": "feed_frozen_prices",
                    "severity": "CRITICAL",
                    "title": f"시세 피드 동결 의심 (전 {len(pairs)}종목 가격 {same_cnt}회 연속 동일)",
                    "details": f"scan_results.json 시각은 갱신되나 가격 벡터({vec_hash}) 완전 고정",
                    "recommendation": "거래소 티커 캐시/피드 고착 가능성 — 스캐너 상태 즉시 확인 필요",
                })
        except Exception:
            pass

    try:
        _atomic_write_json(FEED_FREEZE_STATE_FILE, new_state)
    except Exception:
        pass

    return {"alerts": alerts, "details": summary}


def check_host_ops_ip_net_power() -> Dict[str, Any]:
    """
    [M33] Local Mac 24/7 Ops:
      1) Dual-venue probe -> activates external network outage shield so bots are NOT falsely restarted.
      2) Public IP change detector (exchange API IP whitelist breaks immediately when ISP IP shifts).
      3) macOS AC Power sleep check (`pmset -g custom`).
    """
    alerts: List[Dict[str, str]] = []
    okx_ok = bool(http_get_json("https://www.okx.com/api/v5/public/time", timeout=4.0)[0])
    bnc_ok = bool(http_get_json("https://fapi.binance.com/fapi/v1/time", timeout=4.0)[0])
    ext_net_ok = okx_ok or bnc_ok

    if not ext_net_ok:
        set_external_network_down(True, "OKX/Binance 공용 타임서버 동시 응답 불가", ttl_sec=180)
        alerts.append({
            "bot_id": "8888",
            "key": "host_external_network_down",
            "severity": "WARN",
            "title": "외부 인터넷/거래소 망 단절 감지 (봇 헛재기동 억제 가동)",
            "details": "OKX·Binance 동시 접속 실패 — 9봇 연쇄 헛재기동을 차단하고 복구 대기 중",
            "recommendation": "Mac 인터넷 연결(Wi-Fi/공유기) 확인 필요",
        })
    else:
        set_external_network_down(False)

    # Public IP tracking (only when internet is reachable)
    host_state = _load_json(HOST_OPS_STATE_FILE, {}) or {}
    cur_ip = ""
    if ext_net_ok:
        ip_doc, _ = http_get_json("https://api.ipify.org?format=json", timeout=4.0)
        if isinstance(ip_doc, dict) and ip_doc.get("ip"):
            cand = str(ip_doc["ip"]).strip()
            if _IP_RE.match(cand):
                cur_ip = cand
        if not cur_ip:
            try:
                cand = subprocess.check_output(["curl", "-sS", "--max-time", "4", "https://ifconfig.me/ip"], text=True).strip()
                if _IP_RE.match(cand):
                    cur_ip = cand
            except Exception:
                pass

    prev_ip = str(host_state.get("public_ip") or "")
    last_change = host_state.get("last_ip_change") or {}
    now_ts = time.time()
    if cur_ip:
        if prev_ip and cur_ip != prev_ip:
            last_change = {
                "from": prev_ip,
                "to": cur_ip,
                "ts": now_ts,
                "ts_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        host_state["public_ip"] = cur_ip
        host_state["last_ip_change"] = last_change
        host_state["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            _atomic_write_json(HOST_OPS_STATE_FILE, host_state)
        except Exception:
            pass

    if last_change and (now_ts - float(last_change.get("ts") or 0.0)) < 86400:
        alerts.append({
            "bot_id": "8888",
            "key": "host_public_ip_changed",
            "severity": "CRITICAL",
            "title": f"공인 IP 변경 감지 ({last_change.get('from')} → {last_change.get('to')})",
            "details": f"변경 시각: {last_change.get('ts_str')} — 거래소 API IP 화이트리스트 차단 가능성 높음",
            "recommendation": "OKX 및 Binance API 키 관리에서 신규 공인 IP 등록 필요",
        })

    # macOS AC Power sleep check
    ac_sleep_val: Optional[int] = None
    try:
        pm_out = subprocess.check_output(["pmset", "-g", "custom"], text=True, timeout=4)
        in_ac = False
        for line in pm_out.splitlines():
            s = line.strip()
            if s.startswith("AC Power:"):
                in_ac = True
                continue
            if in_ac and s.endswith(":") and not s.startswith("AC Power"):
                break
            if in_ac:
                m = re.match(r"^sleep\s+(\d+)", s)
                if m:
                    ac_sleep_val = int(m.group(1))
                    break
        if ac_sleep_val is not None and ac_sleep_val > 0:
            alerts.append({
                "bot_id": "8888",
                "key": "host_ac_sleep_enabled",
                "severity": "WARN",
                "title": f"Mac AC 전원 자동절전 활성화 감지 (sleep={ac_sleep_val}분)",
                "details": "24시간 자동매매 서버의 AC 전원 sleep=0 비활성화 권장",
                "recommendation": "macOS 전원 설정 또는 sudo pmset -c sleep 0 적용 검토",
            })
    except Exception:
        pass

    return {
        "alerts": alerts,
        "details": {
            "ext_network_ok": ext_net_ok,
            "okx_ok": okx_ok,
            "binance_ok": bnc_ok,
            "public_ip": cur_ip or prev_ip,
            "ac_sleep": ac_sleep_val,
        },
    }


def _backup_today(bots: List[int]) -> Dict[str, Any]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    dest_dir = os.path.join(BACKUP_ROOT, today_str)
    done_marker = os.path.join(dest_dir, ".done")
    status = {"date": today_str, "ran_now": False, "copied_files": 0, "pruned_dirs": []}

    if not os.path.exists(done_marker):
        try:
            os.makedirs(dest_dir, exist_ok=True)
            copied = 0
            for b in bots:
                bs = str(b)
                bdir = os.path.join(BASE_PROJECT, bs)
                if not os.path.isdir(bdir):
                    continue
                b_dest = os.path.join(dest_dir, bs)
                os.makedirs(b_dest, exist_ok=True)
                for rel in (
                    "config.json",
                    "data/trade_history.csv",
                    "data/stats.json",
                    "data/active_positions.json",
                    "data/engine_states.json",
                ):
                    src = os.path.join(bdir, rel)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(b_dest, os.path.basename(rel)))
                        copied += 1

            c_dest = os.path.join(dest_dir, "8888")
            os.makedirs(c_dest, exist_ok=True)
            for rel in (
                "seeds.json",
                "snapshots.json",
                "peak_assets.json",
                "strategy_baselines.json",
                "data/proactive_alerts.json",
                "data/watchdog_scorecard.json",
            ):
                src = os.path.join(BASE_8888, rel)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(c_dest, os.path.basename(rel)))
                    copied += 1

            with open(done_marker, "w", encoding="utf-8") as mf:
                mf.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            status["ran_now"] = True
            status["copied_files"] = copied
        except Exception as e:
            status["error"] = str(e)

    # Prune backups older than 14 days
    if os.path.isdir(BACKUP_ROOT):
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        for name in sorted(os.listdir(BACKUP_ROOT)):
            if re.match(r"^\d{4}-\d{2}-\d{2}$", name) and name < cutoff:
                full = os.path.join(BACKUP_ROOT, name)
                if os.path.isdir(full):
                    try:
                        shutil.rmtree(full)
                        status["pruned_dirs"].append(name)
                    except Exception:
                        pass
    return status


def check_alert_channels_and_backup_ledgers(
    bots: List[int],
    include_canary: bool = False,
    ext_network_ok: bool = True,
) -> Dict[str, Any]:
    """[M34] Alert channel liveness canary (non-spamming GET), CSV/JSON integrity, and daily 14d backup."""
    alerts: List[Dict[str, str]] = []
    canary_res: Dict[str, Any] = {"checked": False}

    # 1) Channel Canary (Telegram getMe + Discord webhook GET)
    if include_canary and ext_network_ok:
        canary_res["checked"] = True
        tg_tok, tg_cid = _load_telegram_creds()
        if tg_tok and tg_cid:
            tg_doc, tg_err = http_get_json(f"https://api.telegram.org/bot{tg_tok}/getMe", timeout=5.0)
            tg_ok = isinstance(tg_doc, dict) and bool(tg_doc.get("ok"))
            canary_res["telegram_ok"] = tg_ok
            if not tg_ok:
                alerts.append({
                    "bot_id": "8888",
                    "key": "canary_telegram_down",
                    "severity": "CRITICAL",
                    "title": "텔레그램 알림 봇 토큰/연결 장애",
                    "details": f"getMe 실패 ({tg_err or tg_doc})",
                    "recommendation": "TELEGRAM_BOT_TOKEN 유효성 점검 필요 (현재 Discord 경보는 활성)",
                })
        dc_url = _load_discord_webhook()
        if dc_url:
            dc_doc, dc_err = http_get_json(dc_url, timeout=5.0)
            dc_ok = isinstance(dc_doc, dict) and bool(dc_doc.get("id"))
            canary_res["discord_ok"] = dc_ok
            if not dc_ok:
                alerts.append({
                    "bot_id": "8888",
                    "key": "canary_discord_down",
                    "severity": "CRITICAL",
                    "title": "디스코드 웹훅 채널 장애",
                    "details": f"Webhook GET 실패 ({dc_err or dc_doc})",
                    "recommendation": "discord_webhook.txt 웹훅 URL 유효성 점검 필요 (Telegram 경보 활성)",
                })
        pro_url = _load_proactive_discord_webhook()
        if pro_url and pro_url != dc_url:
            pro_doc, pro_err = http_get_json(pro_url, timeout=5.0)
            pro_ok = isinstance(pro_doc, dict) and bool(pro_doc.get("id"))
            canary_res["proactive_discord_ok"] = pro_ok
            if not pro_ok:
                alerts.append({
                    "bot_id": "8888",
                    "key": "canary_proactive_discord_down",
                    "severity": "CRITICAL",
                    "title": "선제 경보 전용 디스코드 웹훅 장애",
                    "details": f"Webhook GET 실패 ({pro_err or pro_doc})",
                    "recommendation": "discord_webhook_proactive.txt 웹훅 URL 유효성 점검 필요",
                })

    # 2) CSV truncation / 0-byte & JSON corruption audit across 9 bots
    prev_state = _load_json(LEDGER_INTEGRITY_FILE, {}) or {}
    new_state: Dict[str, Dict[str, int]] = {}
    corrupted: Dict[str, List[str]] = {}
    truncated: Dict[str, str] = {}

    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if not os.path.isdir(bdir) or os.path.exists(os.path.join(bdir, ".stopped")):
            continue

        bad_json = []
        for rel in ("config.json", "data/stats.json", "data/active_positions.json"):
            jp = os.path.join(bdir, rel)
            if os.path.exists(jp):
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        json.load(f)
                except Exception as je:
                    bad_json.append(f"{rel}({je})")
        if bad_json:
            corrupted[bs] = bad_json
            alerts.append({
                "bot_id": bs,
                "key": "security_json_corrupted",
                "severity": "CRITICAL",
                "title": f"핵심 JSON 파일 손상 ({len(bad_json)}건)",
                "details": " | ".join(bad_json),
                "recommendation": f"/Users/l/project/8888/backups 일일 백업에서 즉시 복원 검토 필요",
            })

        csv_p = os.path.join(bdir, "data", "trade_history.csv")
        if os.path.exists(csv_p):
            try:
                sz = os.path.getsize(csv_p)
                with open(csv_p, "r", encoding="utf-8-sig", errors="ignore") as f:
                    lines = sum(1 for ln in f if ln.strip())
                prev_bot = prev_state.get(bs) or {}
                prev_sz = int(prev_bot.get("size") or 0)
                prev_ln = int(prev_bot.get("lines") or 0)
                if (prev_sz > 200 and sz == 0) or (prev_ln > 10 and lines + 2 < prev_ln):
                    truncated[bs] = f"lines:{prev_ln}->{lines}, size:{prev_sz}->{sz}"
                    alerts.append({
                        "bot_id": bs,
                        "key": "security_ledger_truncated",
                        "severity": "CRITICAL",
                        "title": f"체결 장부(CSV) 행 급감/초기화 감지 ({prev_ln}→{lines}행)",
                        "details": truncated[bs],
                        "recommendation": "비정상 파일 덮어쓰기 의심 — backups/ 최신 백업 대조 및 복원 필요",
                    })
                new_state[bs] = {"size": sz, "lines": lines}
            except Exception:
                pass

    try:
        _atomic_write_json(LEDGER_INTEGRITY_FILE, new_state)
    except Exception:
        pass

    # 3) Daily 14-day backup
    backup_status = _backup_today(bots)

    return {
        "alerts": alerts,
        "details": {
            "canary": canary_res,
            "corrupted_json": corrupted,
            "truncated_csv": truncated,
            "daily_backup": backup_status,
        },
    }


def run_security_ops_audit(bots: List[int], include_canary: bool = False) -> Dict[str, Any]:
    """Run M28/M29-env/M32/M33/M34 checks, persist security_ops_health.json, and return unified alerts."""
    m33 = check_host_ops_ip_net_power()
    ext_net_ok = bool((m33.get("details") or {}).get("ext_network_ok", True))
    m28 = check_usdt_depeg() if ext_net_ok else {"alerts": [], "details": {"skipped": "ext_net_down"}}
    m29 = check_env_file_security(bots)
    m32 = check_frozen_market_feeds(bots)
    m34 = check_alert_channels_and_backup_ledgers(bots, include_canary=include_canary, ext_network_ok=ext_net_ok)

    all_alerts = m28["alerts"] + m29["alerts"] + m32["alerts"] + m33["alerts"] + m34["alerts"]
    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "m28_usdt_peg": m28["details"],
        "m29_env_perms": m29["details"],
        "m32_feed_freeze": m32["details"],
        "m33_host_ops": m33["details"],
        "m34_canary_ledger_backup": m34["details"],
        "alert_count": len(all_alerts),
    }
    try:
        _atomic_write_json(SECURITY_OPS_HEALTH_FILE, payload)
    except Exception:
        pass
    return {"alerts": all_alerts, "summary": payload}
