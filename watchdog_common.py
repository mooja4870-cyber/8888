#!/usr/bin/env python3
"""
8888 Watchdog Shared Infrastructure (`watchdog_common.py`).

Provides:
1. Single-sink deduplicated logging (eliminates double writes when launched via `watchdog_keeper.sh >> log 2>&1`).
2. Precompiled, low-CPU log error matcher (pre-cleans `error_dict.txt` once at startup into a single regex).
3. Cross-watchdog per-bot restart locking (`fcntl.flock`) + global cooldown state (`/tmp/watchdog_restart_state.json`).
4. Proactive threshold & lifecycle breach alert registry (`data/proactive_alerts.json`) + Discord notifications.
5. Runtime-safe config read/validation without silent auto-mutation.
"""
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Tuple

BASE_8888 = "/Users/l/project/8888"
BASE_PROJECT = "/Users/l/project"
RESTART_STATE_FILE = "/tmp/watchdog_restart_state.json"
RESTART_STATE_LOCK = "/tmp/watchdog_restart_state.lock"
PROACTIVE_ALERTS_FILE = os.path.join(BASE_8888, "data", "proactive_alerts.json")
PROACTIVE_ALERTS_LOCK = "/tmp/watchdog_proactive_alerts.lock"
HEARTBEAT_FILE = os.path.join(BASE_8888, "data", "watchdog_heartbeat.json")
HEARTBEAT_LOCK = "/tmp/watchdog_heartbeat.lock"
MAINTENANCE_FLAG_FILE = "/tmp/watchdog_maintenance.json"
MAX_MAINTENANCE_TTL_SEC = 600

_ALNUM_RE = re.compile(r"[^a-z0-9가-힣]")
_LOG_LOCK = threading.Lock()

# Normal operational trading/telemetry tags in `error_dict.txt` that must NEVER trigger crash restarts
_BENIGN_TAGS = (
    "[trailing stop]",
    "[timeout exit]",
    "[high roi guard]",
    "[mode sync]",
    "[skip]",
    "[entry block]",
    "[m4 sizing]",
    "[pnl sync]",
    "[dash]",
    "[be guard]",
    "[reconciliation]",
    "[on blue]",
    "[regime]",
    "[ws] mockclient",
    "🚀 [tp breakout]",
    "🛡️ [drawdown guard]",
    "⚠️ [danger zone sizing]",
    "[order result]",
    "-5022",
    "could not be executed as maker",
)

_DOCSTRING_NOISE_RE = re.compile(
    r"(spline|quantile|matplotlib|pytest|snowpark|categorical|multiindex|lucas_prp|"
    r"lineoffsets|nonuniformimage|secondary_xaxis|invalid wheel|broadcast|matrix|"
    r"matrices|tensor|column order|invalid norm order)",
    re.I,
)

_GENUINE_ERR_RE = re.compile(
    r"([가-힣]|^\[.*?(실패|오류|에러|예외|차단|누락|긴급|정지|불일치|미확인|감지|경고|critical|fail|error|timeout)|"
    r"traceback|exception|error:|errno|401|403|418|429|500|502|503|504|timed? out|"
    r"insufficient|rate ?limit|too many|connection|ssl|eof|jsondecode|ccxt|okx|binance|notional)",
    re.I,
)

# Transient single-call market/network lines that should require repeat threshold (not instant bounce)
TRANSIENT_HINTS = (
    "ohlcv 조회 실패",
    "does not have market symbol",
    "ratelimit",
    "rate limit",
    "networkerror",
    "timed out",
    "timeout",
    "스캐너 tickers",
    "hover 차트 조회 실패",
    "timestamp ahead error detected",
)

# Structural / exchange parameter or auth/IP errors that restarting the bot cannot fix
NON_RESTART_STRUCTURAL_HINTS = (
    "-4164",
    "order's notional must be no smaller than",
    "-4067",
    "position side cannot be changed",
    "마진모드 설정 실패",
    "-2015",
    "50111",
    "50113",
    "invalid api-key",
    "ip not in whitelist",
    "api-key format invalid",
    "api key expired",
    "permission denied",
)

_CIRCUIT_EXEMPT_PREFIXES = ("프로세스 중단", "cpu 폭주", "silent crash", "좀비")


def _error_signature(reason: str) -> str:
    """Normalize an error line into a stable short signature for repeat-restart circuit breaking."""
    raw = str(reason or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if any(p in low for p in _CIRCUIT_EXEMPT_PREFIXES):
        return ""
    m = re.search(r"-\d{4}", raw)
    if m:
        return m.group(0)
    stripped = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?\s*", "", low)
    stripped = re.sub(r"\d+(?:\.\d+)?", "", stripped)
    return _ALNUM_RE.sub("", stripped)[:36]


def record_restart_attempt_and_check_breaker(
    bot_name: str,
    reason: str,
    window_sec: int = 3600,
    max_same_sig: int = 2,
) -> Tuple[bool, int, str]:
    """
    Check whether restarting `bot_name` for `reason` has already been attempted `max_same_sig`
    or more times within `window_sec`. Process-down/CPU/silent crashes are exempt.
    """
    sig = _error_signature(reason)
    if not sig:
        return False, 0, ""

    now = time.time()
    with open(RESTART_STATE_LOCK, "w") as sf:
        fcntl.flock(sf.fileno(), fcntl.LOCK_EX)
        try:
            state = _read_restart_state_unlocked()
            rec = dict(state.get(bot_name) or {})
            attempts = [
                a for a in (rec.get("recent_attempts") or [])
                if isinstance(a, dict) and (now - float(a.get("ts") or 0.0)) <= window_sec
            ]
            rec["recent_attempts"] = attempts
            state[bot_name] = rec
            _write_restart_state_unlocked(state)
            same_cnt = sum(1 for a in attempts if a.get("sig") == sig)
            return (same_cnt >= max_same_sig), same_cnt, sig
        finally:
            fcntl.flock(sf.fileno(), fcntl.LOCK_UN)


def setup_clean_logger(log_file: str) -> Callable[[str], None]:
    """Return a single-sink logger that never double-writes when stdout is already redirected to `log_file`."""
    stdout_same_as_file = False
    try:
        st_out = os.fstat(sys.stdout.fileno())
        if os.path.exists(log_file):
            st_file = os.stat(log_file)
            stdout_same_as_file = (st_out.st_dev == st_file.st_dev and st_out.st_ino == st_file.st_ino)
    except Exception:
        stdout_same_as_file = False

    def _log(msg: str) -> None:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        with _LOG_LOCK:
            if stdout_same_as_file:
                print(line, flush=True)
            else:
                try:
                    os.makedirs(os.path.dirname(log_file), exist_ok=True)
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass
                try:
                    if sys.stdout.isatty():
                        print(line, flush=True)
                except Exception:
                    pass

    return _log


class BotErrorMatcher:
    """Fast precompiled log error detector (<0.2% CPU across all bots)."""

    def __init__(self, dict_path: str, fatal_keywords=(), static_keywords=()):
        self.fatal_lower = tuple(k.lower() for k in fatal_keywords if k)
        self.static_lower = tuple(k.lower() for k in static_keywords if k)
        clean_set = []
        seen = set()
        if dict_path and os.path.exists(dict_path):
            try:
                with open(dict_path, "r", encoding="utf-8") as f:
                    for raw in f:
                        kw = raw.strip()
                        if not kw:
                            continue
                        ll = kw.lower()
                        if any(tag in ll for tag in _BENIGN_TAGS) or _DOCSTRING_NOISE_RE.search(kw):
                            continue
                        if not _GENUINE_ERR_RE.search(kw):
                            continue
                        c = _ALNUM_RE.sub("", ll)
                        if len(c) >= 5 and c not in seen:
                            seen.add(c)
                            clean_set.append(c)
            except Exception:
                pass
        # Longest patterns first so single compiled union regex finds exact meaningful errors quickly
        clean_set.sort(key=len, reverse=True)
        self.dict_pattern: Optional[re.Pattern] = (
            re.compile("|".join(re.escape(c) for c in clean_set)) if clean_set else None
        )
        self.keyword_count = len(clean_set)

    def classify_line(self, line: str) -> Tuple[bool, bool, bool, str]:
        """Return (is_error, is_fatal, is_transient, matched_keyword)."""
        if not line:
            return False, False, False, ""
        ll = line.lower()

        # Explicit harmless log tags or lock-refusal exit messages handled elsewhere
        if "[lock]" in ll and "중복 방지" in ll:
            return False, False, True, "lock_guard"
        if "진입유실 방지" in ll or "cancelallorders() is not supported yet" in ll or ("[info]" in ll and "exception" not in ll and "error" not in ll and "traceback" not in ll):
            return False, False, False, ""
        if "[info]" in ll and "[order result]" in ll and "'order_id':" in ll and "'order_id': none" not in ll:
            return False, False, False, ""
        if "-5022" in ll or "could not be executed as maker" in ll:
            return False, False, False, ""

        for fk in self.fatal_lower:
            if fk in ll:
                return True, True, False, fk

        matched = ""
        for sk in self.static_lower:
            if sk in ll:
                matched = sk
                break

        if not matched and self.dict_pattern is not None:
            cleaned = _ALNUM_RE.sub("", ll)
            if len(cleaned) >= 5:
                m = self.dict_pattern.search(cleaned)
                if m:
                    matched = m.group(0)

        if not matched:
            return False, False, False, ""

        is_transient = any(t in ll for t in TRANSIENT_HINTS) and not any(
            c in ll for c in ("oco", "보호주문", "강제청산", "fail-safe", "liquidation")
        )
        return True, False, is_transient, matched


def _read_restart_state_unlocked() -> dict:
    try:
        if os.path.exists(RESTART_STATE_FILE):
            with open(RESTART_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _write_restart_state_unlocked(state: dict) -> None:
    tmp = RESTART_STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, RESTART_STATE_FILE)


def bot_restart_locked(
    bot_name: str,
    bot_dir: str,
    source: str,
    reason: str = "",
    cooldown_sec: int = 120,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Safely restart a bot using `bash run.sh` under a shared cross-watchdog per-bot `fcntl.flock`
    and global cooldown timer so multiple watchdogs never collide or spawn duplicate bot PIDs.
    """
    lock_path = f"/tmp/watchdog_restart_{bot_name}.lock"
    run_script = os.path.join(bot_dir, "run.sh")
    if not os.path.exists(run_script):
        return False, "run.sh_missing"

    lf = open(lock_path, "w")
    try:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False, "restart_lock_held"

        now = time.time()
        with open(RESTART_STATE_LOCK, "w") as sf:
            fcntl.flock(sf.fileno(), fcntl.LOCK_EX)
            try:
                state = _read_restart_state_unlocked()
                rec = state.get(bot_name) or {}
                last_ts = float(rec.get("last_restart_ts") or 0.0)
                if now - last_ts < cooldown_sec:
                    rem = int(cooldown_sec - (now - last_ts))
                    return False, f"global_cooldown_{rem}s_by_{rec.get('source', '?')}"
                prev_attempts = [
                    a for a in (rec.get("recent_attempts") or [])
                    if isinstance(a, dict) and (now - float(a.get("ts") or 0.0)) <= 3600
                ]
                sig = _error_signature(reason)
                if sig:
                    prev_attempts.append({"ts": now, "sig": sig})
                state[bot_name] = {
                    "last_restart_ts": now,
                    "source": source,
                    "reason": str(reason)[:200],
                    "status": "starting",
                    "recent_attempts": prev_attempts[-20:],
                }
                _write_restart_state_unlocked(state)
            finally:
                fcntl.flock(sf.fileno(), fcntl.LOCK_UN)

        if log_fn:
            log_fn(f"[{bot_name}] 🔒 Shared restart lock acquired ({source}): {reason[:120]}")

        res = subprocess.run(
            ["bash", "run.sh"],
            cwd=bot_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        out_tail = " | ".join(
            l.strip() for l in (res.stdout or "").splitlines() if "✅" in l or "❌" in l or "엔진 PID" in l
        )[-240:]

        with open(RESTART_STATE_LOCK, "w") as sf:
            fcntl.flock(sf.fileno(), fcntl.LOCK_EX)
            try:
                state = _read_restart_state_unlocked()
                rec = state.get(bot_name) or {}
                state[bot_name] = {
                    "last_restart_ts": time.time(),
                    "source": source,
                    "reason": str(reason)[:200],
                    "status": "ok" if res.returncode == 0 else f"rc={res.returncode}",
                    "summary": out_tail,
                    "recent_attempts": rec.get("recent_attempts") or [],
                }
                _write_restart_state_unlocked(state)
            finally:
                fcntl.flock(sf.fileno(), fcntl.LOCK_UN)

        return (res.returncode == 0), (out_tail or f"rc={res.returncode}")
    except subprocess.TimeoutExpired:
        return False, "run.sh_timeout_60s"
    except Exception as e:
        return False, f"restart_exc:{e}"
    finally:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lf.close()


def _send_discord(msg: str) -> None:
    try:
        if BASE_8888 not in sys.path:
            sys.path.insert(0, BASE_8888)
        import discord_alert
        discord_alert._post(msg)
    except Exception:
        pass


def _load_telegram_creds() -> Tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    for env_path in (os.path.join(BASE_8888, ".env"), os.path.join(BASE_PROJECT, "8401", ".env")):
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "TELEGRAM_BOT_TOKEN" and v and not token:
                        token = v
                    elif k == "TELEGRAM_CHAT_ID" and v and not chat_id:
                        chat_id = v
        except Exception:
            pass
        if token and chat_id:
            break
    return token, chat_id


def _build_ssl_context():
    try:
        import ssl
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def http_get_json(url: str, timeout: float = 6.0):
    """Fetch JSON over HTTPS with certifi SSL fallback + curl fallback for macOS Python runtimes."""
    import urllib.request

    ctx = _build_ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "8888-AegisWatchdog/6.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw), ""
    except Exception as ur_err:
        try:
            raw = subprocess.check_output(
                ["curl", "-sS", "--max-time", str(int(max(2, round(timeout)))), url],
                text=True,
                stderr=subprocess.PIPE,
                timeout=timeout + 2,
            )
            if raw and raw.strip():
                return json.loads(raw), ""
            return None, f"empty curl response ({ur_err})"
        except Exception as c_err:
            return None, f"{ur_err} | curl: {c_err}"


def rotate_log_copytruncate(log_file: str, max_bytes: int = 10 * 1024 * 1024, keep: int = 3) -> bool:
    """Safely rotate O_APPEND / stdout-redirected logs without breaking open file descriptors."""
    try:
        if not log_file or not os.path.exists(log_file):
            return False
        if os.path.getsize(log_file) <= max_bytes:
            return False
        import shutil
        for idx in range(keep, 1, -1):
            src = f"{log_file}.{idx - 1}"
            dst = f"{log_file}.{idx}"
            if os.path.exists(src):
                os.replace(src, dst)
        shutil.copy2(log_file, f"{log_file}.1")
        with open(log_file, "r+", encoding="utf-8", errors="ignore") as f:
            f.truncate(0)
        return True
    except Exception:
        return False


def update_watchdog_heartbeat(role_name: str, extra: Optional[dict] = None) -> None:
    """[M19 Dead-Man's Switch] Persist periodic daemon heartbeat lease under flock."""
    os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
    now = time.time()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(HEARTBEAT_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = {"heartbeats": {}, "updated": now_str}
            if os.path.exists(HEARTBEAT_FILE):
                try:
                    with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            doc = loaded
                except Exception:
                    pass
            doc.setdefault("heartbeats", {})[str(role_name)] = {
                "pid": os.getpid(),
                "ts": now,
                "ts_str": now_str,
                "extra": extra or {},
            }
            doc["updated"] = now_str
            tmp = HEARTBEAT_FILE + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            os.replace(tmp, HEARTBEAT_FILE)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def set_maintenance_window(ttl_sec: int = 300, reason: str = "") -> dict:
    """[M19] Activate auto-expiring maintenance window (clamped <= MAX_MAINTENANCE_TTL_SEC=600s)."""
    ttl = max(30, min(int(ttl_sec or 300), MAX_MAINTENANCE_TTL_SEC))
    now = time.time()
    payload = {
        "created_ts": now,
        "expires_ts": now + ttl,
        "ttl_sec": ttl,
        "reason": str(reason or "manual maintenance")[:160],
        "expires_at": dt.datetime.fromtimestamp(now + ttl).strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = MAINTENANCE_FLAG_FILE + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MAINTENANCE_FLAG_FILE)
    return payload


def clear_maintenance_window() -> bool:
    try:
        if os.path.exists(MAINTENANCE_FLAG_FILE):
            os.remove(MAINTENANCE_FLAG_FILE)
            return True
    except Exception:
        pass
    return False


def is_maintenance_active() -> Tuple[bool, str]:
    """Return (active, reason); automatically deletes expired maintenance lock."""
    if not os.path.exists(MAINTENANCE_FLAG_FILE):
        return False, ""
    try:
        with open(MAINTENANCE_FLAG_FILE, "r", encoding="utf-8") as f:
            doc = json.load(f)
        exp = float(doc.get("expires_ts") or 0.0)
        if time.time() <= exp:
            rem = int(exp - time.time())
            return True, f"{doc.get('reason', 'maintenance')} (남은 {rem}s)"
        clear_maintenance_window()
    except Exception:
        clear_maintenance_window()
    return False, ""


def _send_telegram(msg: str) -> None:
    try:
        import urllib.request
        token, chat_id = _load_telegram_creds()
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        raw_payload = json.dumps({"chat_id": chat_id, "text": msg}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5, context=_build_ssl_context()):
                return
        except Exception:
            subprocess.run(
                [
                    "curl", "-sS", "--max-time", "5", "-X", "POST",
                    "-H", "Content-Type: application/json",
                    "-d", raw_payload.decode("utf-8"),
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=7,
            )
    except Exception:
        pass


def load_proactive_alerts() -> dict:
    if not os.path.exists(PROACTIVE_ALERTS_FILE):
        return {"active": {}, "history": [], "updated": None}
    try:
        with open(PROACTIVE_ALERTS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("active", {})
                d.setdefault("history", [])
                return d
    except Exception:
        pass
    return {"active": {}, "history": [], "updated": None}


def _save_proactive_alerts_unlocked(data: dict) -> None:
    tmp = PROACTIVE_ALERTS_FILE + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROACTIVE_ALERTS_FILE)


def record_proactive_alert(
    bot_id: str,
    alert_key: str,
    severity: str,
    title: str,
    details: str,
    recommendation: str = "",
    cooldown_sec: int = 21600,
    notify_discord: bool = True,
    escalation_sec: int = 7200,
) -> bool:
    """
    [M25 Unified Routing]
    Record an active threshold/lifecycle breach for dashboard rendering + severity-routed alerts:
      - INFO: local registry only (no external spam unless explicitly requested)
      - WARN: Discord alert respecting cooldown_sec
      - CRITICAL: Discord + Telegram simultaneously, plus 2h unresolved re-escalation (up to 6x)
    """
    os.makedirs(os.path.dirname(PROACTIVE_ALERTS_FILE), exist_ok=True)
    key = f"{bot_id}:{alert_key}"
    sev = str(severity or "WARN").upper()
    now = time.time()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    should_notify = False
    is_escalation = False
    esc_count = 0

    with open(PROACTIVE_ALERTS_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            data = load_proactive_alerts()
            prev = data["active"].get(key) or {}
            last_notified = float(prev.get("last_notified_ts") or 0.0)
            first_seen = prev.get("first_seen") or now_str
            esc_count = int(prev.get("escalation_count") or 0)

            allow_ext = notify_discord and (sev != "INFO")
            cooldown_due = allow_ext and ((now - last_notified) >= cooldown_sec)
            escalation_due = (
                allow_ext
                and sev == "CRITICAL"
                and last_notified > 0
                and ((now - last_notified) >= escalation_sec)
                and esc_count < 6
            )
            should_notify = cooldown_due or escalation_due
            if escalation_due and not cooldown_due:
                is_escalation = True
                esc_count += 1
            elif cooldown_due and last_notified == 0:
                esc_count = 0

            entry = {
                "key": key,
                "bot_id": str(bot_id),
                "alert_key": alert_key,
                "severity": sev,
                "title": title,
                "details": details,
                "recommendation": recommendation,
                "first_seen": first_seen,
                "last_seen": now_str,
                "last_notified_ts": now if should_notify else last_notified,
                "escalation_count": esc_count,
            }
            data["active"][key] = entry
            data["updated"] = now_str
            if should_notify:
                data["history"].append({
                    "ts": now_str,
                    "bot_id": str(bot_id),
                    "severity": sev,
                    "title": title,
                    "details": details,
                    "recommendation": recommendation,
                    "escalated": is_escalation,
                })
                data["history"] = data["history"][-150:]
            _save_proactive_alerts_unlocked(data)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    if should_notify:
        icon = "🚨" if sev == "CRITICAL" else "⚠️"
        esc_tag = f"[미해소 에스컬레이션 #{esc_count}] " if is_escalation else ""
        target_label = "중앙 관제(8888)" if str(bot_id) == "8888" else f"{bot_id}봇"
        msg = (
            f"{icon} **[{esc_tag}8888 선제 경보 / {target_label}]** `{title}`\n"
            f"• 관측 수치: {details}\n"
        )
        if recommendation:
            msg += f"• 권고 조치 (보스 승인 대기): {recommendation}\n"
        msg += "• 원칙: 승인 없는 전략·설정 자동 변경 차단 상태"
        _send_discord(msg)
        if sev == "CRITICAL":
            _send_telegram(msg)
    return should_notify


def clear_proactive_alert(bot_id: str, alert_key: str) -> None:
    if not os.path.exists(PROACTIVE_ALERTS_FILE):
        return
    key = f"{bot_id}:{alert_key}"
    with open(PROACTIVE_ALERTS_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            data = load_proactive_alerts()
            if key in data["active"]:
                data["active"].pop(key, None)
                data["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _save_proactive_alerts_unlocked(data)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def prune_expired_proactive_alerts(max_age_sec: int = 7200) -> int:
    """Remove expired repeat_restart_* / structural_* alerts after max_age_sec without recurrence."""
    if not os.path.exists(PROACTIVE_ALERTS_FILE):
        return 0
    now_dt = dt.datetime.now()
    removed = 0
    with open(PROACTIVE_ALERTS_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            data = load_proactive_alerts()
            active = data.get("active") or {}
            to_del = []
            for k, v in active.items():
                akey = str((v or {}).get("alert_key") or "")
                if not (akey.startswith("repeat_restart_") or akey.startswith("structural_")):
                    continue
                ls = str((v or {}).get("last_seen") or "").strip()
                try:
                    last_dt = dt.datetime.strptime(ls[:19], "%Y-%m-%d %H:%M:%S")
                    if (now_dt - last_dt).total_seconds() > max_age_sec:
                        to_del.append(k)
                except Exception:
                    pass
            for k in to_del:
                active.pop(k, None)
                removed += 1
            if removed > 0:
                data["updated"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                _save_proactive_alerts_unlocked(data)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return removed


def get_bot_processes(bots) -> dict:
    """Single `ps` pass returning `{bot_name: (pid, pcpu)}` for all requested bots."""
    proc_map = {str(b): (None, 0.0) for b in bots}
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,pcpu,command"], text=True)
        for line in out.splitlines():
            if "bot.py" not in line or "watchdog" in line or "grep" in line:
                continue
            for b in bots:
                bs = str(b)
                if f"/{bs}/bot.py" in line or f" {bs}/bot.py" in line or (bs in line and "bot.py" in line):
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        try:
                            proc_map[bs] = (int(parts[0]), float(parts[1]))
                        except ValueError:
                            proc_map[bs] = (int(parts[0]), 0.0)
                    break
    except Exception:
        pass
    return proc_map


def run_log_watchdog(
    role_name: str,
    banner: str,
    startup_notice: str,
    heartbeat_notice: str,
    log_file: str,
    dict_path: str,
    bots,
    fatal_keywords,
    static_keywords,
    alert_tag: str,
    allow_fatal_pause: bool = False,
    check_interval: int = 20,
    silent_timeout: int = 1800,
    max_log_size: int = 5 * 1024 * 1024,
) -> None:
    """Shared lightweight log/process/CPU/silent-crash watchdog loop with flock restart serialization."""
    import signal

    log = setup_clean_logger(log_file)
    matcher = BotErrorMatcher(dict_path, fatal_keywords=fatal_keywords, static_keywords=static_keywords)

    def _post_tag(msg: str) -> None:
        _send_discord(f"🚨 [{alert_tag}] {msg}")

    # Log rotation check without breaking O_APPEND / stdout-redirected file descriptors
    def _maybe_rotate() -> None:
        rotate_log_copytruncate(log_file, max_bytes=max(max_log_size, 10 * 1024 * 1024), keep=3)

    log(f"{banner} (matched_sigs={matcher.keyword_count})")
    _post_tag(startup_notice)

    last_offsets = {}
    transient_ts = {b: [] for b in bots}
    for b in bots:
        for lg in ("bot_engine.log", "app.log"):
            lp = os.path.join(BASE_PROJECT, b, lg)
            try:
                if os.path.exists(lp):
                    last_offsets[lp] = os.path.getsize(lp)
            except Exception:
                pass

    last_heartbeat = time.time()

    def _jump_offsets_to_eof(bot_name: str) -> None:
        for lg in ("bot_engine.log", "app.log"):
            lp = os.path.join(BASE_PROJECT, bot_name, lg)
            try:
                last_offsets[lp] = os.path.getsize(lp) if os.path.exists(lp) else 0
            except Exception:
                last_offsets[lp] = 0
        transient_ts[bot_name] = []

    def _inspect_logs(bot_name: str):
        now = time.time()
        latest_mtime = 0.0
        found_err = False
        is_fatal = False
        err_msg = ""

        for lg in ("bot_engine.log", "app.log"):
            lp = os.path.join(BASE_PROJECT, bot_name, lg)
            if not os.path.exists(lp):
                continue
            try:
                mt = os.path.getmtime(lp)
                if mt > latest_mtime:
                    latest_mtime = mt
                cur_sz = os.path.getsize(lp)
                prev_off = last_offsets.get(lp, cur_sz)
                if cur_sz < prev_off:
                    prev_off = 0
                if cur_sz == prev_off:
                    continue
                with open(lp, "rb") as f:
                    f.seek(prev_off)
                    chunk = f.read().decode("utf-8", errors="ignore")
                    last_offsets[lp] = f.tell()
                for line in chunk.splitlines():
                    is_err, fatal, transient, _ = matcher.classify_line(line)
                    if not is_err:
                        continue
                    if fatal:
                        return True, True, False, line.strip()
                    if transient:
                        ts_list = [t for t in transient_ts[bot_name] if now - t <= 300]
                        ts_list.append(now)
                        transient_ts[bot_name] = ts_list
                        if len(ts_list) >= 3:
                            found_err = True
                            err_msg = f"반복 일시 장애(3회/5m): {line.strip()}"
                        continue
                    found_err = True
                    err_msg = line.strip()
            except Exception:
                pass
            if found_err:
                break

        if not found_err and latest_mtime > 0 and (now - latest_mtime > silent_timeout):
            return True, False, True, f"Silent Crash: {silent_timeout // 60}분 이상 로그 갱신 없음"
        return found_err, is_fatal, False, err_msg

    def _handle_issue(bot_name: str, reason: str, fatal: bool = False) -> bool:
        bot_dir = os.path.join(BASE_PROJECT, bot_name)
        cb_file = os.path.join(bot_dir, ".circuit_breaker")
        pause_file = os.path.join(bot_dir, ".pause")
        if os.path.exists(cb_file) or os.path.exists(pause_file):
            return False

        if fatal and allow_fatal_pause:
            proc = get_bot_processes([bot_name]).get(bot_name, (None, 0.0))[0]
            if proc:
                try:
                    os.kill(proc, signal.SIGTERM)
                except Exception:
                    pass
            try:
                with open(pause_file, "w") as pf:
                    pf.write(f"Fatal error ({role_name}): {reason[:120]}")
            except Exception:
                pass
            log(f"[{bot_name}] 치명적 에러로 강제 Pause: {reason[:120]}")
            _post_tag(f"봇 **{bot_name}** 치명적 에러.\n사유: `{reason[:120]}`\n`.pause` 처리(수동 조치 요망).")
            record_proactive_alert(
                bot_name,
                "fatal_runtime_error",
                "CRITICAL",
                "치명적 런타임 에러 발생 (.pause)",
                reason[:160],
                "거래소 잔고/마진모드/포지션모드 확인 후 .pause 해제 검토",
            )
            return True

        if not fatal and any(h in str(reason or "").lower() for h in NON_RESTART_STRUCTURAL_HINTS):
            sig = _error_signature(reason) or "structural"
            _jump_offsets_to_eof(bot_name)
            log(f"[{bot_name}] 🧩 구조적 주문/모드 오류 감지(재기동 생략, {sig}): {reason[:140]}")
            record_proactive_alert(
                bot_name,
                f"structural_{sig}",
                "CRITICAL",
                f"구조적 주문/모드 오류 감지 ({sig})",
                reason[:200],
                "재기동으로 해결 불가한 파라미터/거래소 규격 오류 — 소스 패치 검토 필요",
                cooldown_sec=3600,
                notify_discord=True,
            )
            return False

        tripped, same_cnt, sig = record_restart_attempt_and_check_breaker(bot_name, reason)
        if tripped:
            _jump_offsets_to_eof(bot_name)
            log(f"[{bot_name}] 🛑 동일 오류 반복 재기동 서킷브레이커 발동({same_cnt}회/60m, sig={sig}) → 추가 재기동 중단")
            record_proactive_alert(
                bot_name,
                f"repeat_restart_{sig}",
                "CRITICAL",
                f"동일 오류 반복 재기동 서킷브레이커 ({same_cnt}회/60m)",
                reason[:200],
                "재기동으로 해결되지 않는 구조적 장애 — 즉시 원인 점검 및 패치 필요",
                cooldown_sec=3600,
                notify_discord=True,
            )
            return False

        ok, detail = bot_restart_locked(bot_name, bot_dir, source=role_name, reason=reason, cooldown_sec=120, log_fn=log)
        if ok:
            log(f"[{bot_name}] 감시 조치 재기동 완료: {reason[:120]} ({detail})")
            _post_tag(f"봇 **{bot_name}** 자동 재기동 완료.\n사유: `{reason[:120]}`")
            _jump_offsets_to_eof(bot_name)
            return True
        if "cooldown" in detail or "lock_held" in detail:
            # Do not treat contention skip as failure or spam logs
            _jump_offsets_to_eof(bot_name)
            return False
        log(f"[{bot_name}] 재기동 보류/실패 ({detail}): {reason[:120]}")
        return False

    while True:
        try:
            _maybe_rotate()
            now = time.time()
            restarted = False

            if now - last_heartbeat >= 3600:
                log(f"[{role_name}] {heartbeat_notice}")
                last_heartbeat = now

            procs = get_bot_processes(bots)
            for b in bots:
                bot_dir = os.path.join(BASE_PROJECT, b)
                if (
                    os.path.exists(os.path.join(bot_dir, ".circuit_breaker"))
                    or os.path.exists(os.path.join(bot_dir, ".pause"))
                    or os.path.exists(os.path.join(bot_dir, ".stopped"))
                ):
                    continue

                pid, pcpu = procs.get(b, (None, 0.0))
                if pid and pcpu > 95.0:
                    log(f"[{b}] CPU Spike({pcpu:.1f}%) 감지 → 공유 락 재기동 요청")
                    if _handle_issue(b, f"CPU 폭주: {pcpu:.1f}%", fatal=False):
                        restarted = True
                        time.sleep(5)
                    continue

                if not pid:
                    if _handle_issue(b, "프로세스 중단(Down)", fatal=False):
                        restarted = True
                        time.sleep(5)
                    continue

                has_err, fatal, silent, msg = _inspect_logs(b)
                if has_err or silent:
                    if _handle_issue(b, msg, fatal=fatal):
                        restarted = True
                        time.sleep(5)

            update_watchdog_heartbeat(role_name, {"bots": len(bots)})

            if not restarted:
                time.sleep(check_interval)
        except Exception as e:
            log(f"[{role_name}] Main Loop Error: {e}")
            time.sleep(check_interval)
