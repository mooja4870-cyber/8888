#!/usr/bin/env python3
"""audit_scheduler.py — 33항목 감사를 주기적으로 돌리고 변화가 있을 때만 알린다.

주기 근거 (2026-09-11 실측)
    전체 감사    38.7초 · API 약 110회   → 원장 조회(항목 21·22)가 90%를 차지
    --fast      12.5초 · API 약 15회    → 원장을 건너뛴 31개 항목

  봇들이 **같은 IP로 거래소 API를 공유**한다. 과거 4봇 동시 사용으로 418 밴을
  맞은 적이 있어, 감사가 봇의 할당량을 잠식하면 본말이 전도된다.
  그래서 2단으로 나눈다.

      경량(--fast)  5분   → 하루 288회 ·  API 4,320회
      전체          60분  → 하루  24회 ·  API 2,640회
                             합계 약 7천회/일 (한도 2,400회/분 대비 무시할 수준)

  33항목 중 즉시 알아야 할 것(무손절 포지션·프로세스 사망·쿨다운 데드락·
  스캐너 정체)은 전부 경량 쪽에 들어 있다. 원장 대사는 성격상 시간 단위로
  충분하다.

알림 규율
  · **매 회차 알리지 않는다.** 직전 결과와 비교해 새로 생긴 FAIL만 보고한다.
  · 해소된 FAIL도 한 번 알린다(복구 확인).
  · 같은 FAIL이 계속되면 침묵한다 — 소음이 쌓이면 아무도 안 본다.

산출물
  data/audit_last.json    최신 결과 (대시보드가 읽어 쓸 수 있다)
  logs/audit_history.log  변화 이력만 누적
"""
import json
import os
import re
import subprocess
import sys
import time
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AUDIT = os.path.join(HERE, "audit_33_items.py")
STATE = os.path.join(ROOT, "data", "audit_last.json")
HIST = os.path.join(ROOT, "logs", "audit_history.log")
PY = "/usr/bin/python3"

FAST_SEC = int(os.getenv("AUDIT_FAST_SEC", "300"))     # 5분
FULL_SEC = int(os.getenv("AUDIT_FULL_SEC", "3600"))    # 60분

LINE = re.compile(r"^\s*([✅❌？－]|\u26a0\ufe0f?)\s*(\d+)\.\s+(\S.*?)\s{2,}(.*)$")
# \u26a0\ufe0f(WARN)는 2코드포인트라 ln[0]로는 \u26a0만 잡힌다. 둘 다 등록한다.
ICON = {"✅": "PASS", "❌": "FAIL", "\u26a0\ufe0f": "WARN", "\u26a0": "WARN",
        "？": "UNK", "－": "N/A"}


def log(msg):
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    print(line, flush=True)
    try:
        with open(HIST, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(fast):
    cmd = [PY, AUDIT] + (["--fast"] if fast else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return None, "감사 실행 타임아웃"
    out = r.stdout
    cur_bot = None
    res = {}
    for ln in out.splitlines():
        m = re.match(r"^\s{2}(\d{4})\s+\(PID", ln)
        if m:
            cur_bot = m.group(1)
            res[cur_bot] = {}
            continue
        if not cur_bot:
            continue
        mm = LINE.match(ln)
        if mm:
            no, name, msg = mm.group(2), mm.group(3).strip(), mm.group(4).strip()
            icon = mm.group(1)
            res[cur_bot][no] = {"name": name, "verdict": ICON.get(icon, "?"), "msg": msg}
    return res, None


def fails(res):
    out = {}
    for bot, items in (res or {}).items():
        for no, v in items.items():
            if v["verdict"] == "FAIL":
                out[f"{bot}:{no}"] = f"[{bot}] {no}. {v['name']} — {v['msg']}"
    return out


WEBHOOK_FILE = os.path.join(ROOT, "discord_webhook.txt")


def notify(msg):
    """디스코드 웹훅으로 보낸다. 실패해도 감사는 계속된다.

    [2026-09-11] 처음에는 봇의 `core.alert.send_telegram_alert`를 빌렸는데
    **8401 .env의 TELEGRAM_BOT_TOKEN이 빈 값**이라 아무데도 가지 않았다.
    실제로 쓰이는 채널은 디스코드다(`discord_state_*.json`이 상시 갱신된다).
    알림 경로는 반드시 **실제 도달 여부로** 확인할 것.
    """
    try:
        with open(WEBHOOK_FILE, encoding="utf-8") as f:
            url = f.read().strip()
    except OSError:
        log("⚠️  디스코드 웹훅 파일 없음 — 알림 생략")
        return
    if not url.startswith("https://discord"):
        log("⚠️  웹훅 형식 이상 — 알림 생략")
        return
    # [2026-09-11] User-Agent가 없으면 디스코드가 **403 Forbidden**으로 막는다.
    # 처음에 UA 없이 보냈다가 전량 거부됐다. 8888/discord_alert.py의 검증된
    # 헤더·폴백 구조를 그대로 따른다(requests 1순위, urllib 2순위).
    headers = {"Content-Type": "application/json",
               "User-Agent": "8888-audit/1.0 (+discord-webhook)"}
    payload = {"content": msg[:1900], "username": "봇 자가진단"}
    try:
        import requests
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 204):
            return
        log(f"⚠️  디스코드 status={r.status_code} {r.text[:80]}")
        return
    except Exception:
        pass
    try:
        import urllib.request
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status not in (200, 204):
                log(f"⚠️  디스코드 응답 {r.status}")
    except Exception as e:
        log(f"⚠️  알림 전송 실패: {str(e)[:80]}")


def main():
    log(f"감사 스케줄러 시작 — 경량 {FAST_SEC}초 · 전체 {FULL_SEC}초")
    prev = {}
    if os.path.exists(STATE):
        try:
            prev = fails(json.load(open(STATE)).get("result", {}))
        except Exception:
            prev = {}
    last_full = 0.0
    while True:
        full = (time.time() - last_full) >= FULL_SEC
        t0 = time.time()
        res, err = run(fast=not full)
        took = time.time() - t0
        if err:
            log(f"⚠️  {err}")
            time.sleep(FAST_SEC)
            continue
        if full:
            last_full = time.time()

        cur = fails(res)
        new = {k: v for k, v in cur.items() if k not in prev}
        gone = {k: v for k, v in prev.items() if k not in cur}

        tally = {}
        for items in res.values():
            for v in items.values():
                tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
        mode = "전체" if full else "경량"
        summary = " · ".join(f"{k} {v}" for k, v in sorted(tally.items()))
        try:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump({"ts": dt.datetime.now().isoformat(), "mode": mode,
                       "took_sec": round(took, 1), "tally": tally, "result": res},
                      open(STATE, "w"), ensure_ascii=False, indent=1)
        except Exception:
            pass

        if new or gone:
            log(f"[{mode}] {summary} ({took:.0f}초)  변화 발생")
            for v in new.values():
                log(f"   ❌ 신규 결함  {v}")
            for v in gone.values():
                log(f"   ✅ 해소 확인  {v}")
            lines = ["🔍 *[봇 자가진단 변화]*"]
            if new:
                lines.append("*새 결함*")
                lines += [f"• {v}" for v in list(new.values())[:8]]
            if gone:
                lines.append("*해소*")
                lines += [f"• {v}" for v in list(gone.values())[:8]]
            notify("\n".join(lines)[:1800])
        else:
            # 변화가 없으면 조용히 넘어간다. 전체 감사만 기록을 남긴다.
            if full:
                log(f"[{mode}] {summary} ({took:.0f}초)  변화 없음")

        prev = cur
        time.sleep(FAST_SEC)


if __name__ == "__main__":
    main()
