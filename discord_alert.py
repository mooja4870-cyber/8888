#!/usr/bin/env python3
"""
8888 → 디스코드 전체 일평균수익률 요약 알림.

8888이 보유한 집계(collect())를 매 1분 webhook으로 1건 발송.
형식(과거 형식 재현):
    📊 전체 일평균수익률 (1.0일)
    +0.70%/일  🔴0.03%↑
    ────────────────
    O 8408  +1.63%  🔴0.10%↑
    O 8405  +1.39%  🔵0.05%↓
    ...
    최근 30분 전체 일평균 추이(%)
     +0.70|              -------
          |        ------
     -0.20|--------
  - 봇은 일평균수익률 내림차순.
  - O=보유중(거래소 증거금), X=무포지션.
  - 변화 아이콘: 직전 발송 대비. 🔴상승↑ / 🔵하락↓ / ⚪변화없음 (수익=빨강 컨벤션).
  - 추이: 1분 단위 전체 일평균 최근 30포인트 ASCII 라인차트.

webhook URL은 discord_webhook.txt(.gitignore)에서 읽는다(평문 시크릿 보호).
직전값·추이 버퍼는 discord_state.json에 저장(앱 재시작 후에도 연속성 유지).
"""
import json
import os
import time
import urllib.request

_DIR = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_FILE = os.path.join(_DIR, "discord_webhook.txt")
STATE_FILE = os.path.join(_DIR, "discord_state.json")

CHART_WIDTH = 30        # 최근 30포인트(=1분×30=30분)
CHART_HEIGHT = 6
USERNAME = "봇 관제"
EPS = 0.005             # 이 값 미만 변화는 '변화없음(⚪)'으로 간주


def _load_webhook():
    try:
        with open(WEBHOOK_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
        return s.get("prev_total"), s.get("prev_bots", {}), s.get("history", [])
    except (OSError, ValueError):
        return None, {}, []


def _save_state(prev_total, prev_bots, history):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"prev_total": prev_total, "prev_bots": prev_bots,
                   "history": history[-CHART_WIDTH:]}, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def _trend(cur, prev):
    """(아이콘, 화살표, 변화량) — 직전값 대비. 수익=빨강 컨벤션: 상승=🔴↑, 하락=🔵↓."""
    if prev is None or cur is None or abs(cur - prev) < EPS:
        return "⚪", "-", 0.0
    d = abs(cur - prev)
    return ("🔴", "↑", d) if cur > prev else ("🔵", "↓", d)


def ascii_chart(vals, width=CHART_WIDTH, height=CHART_HEIGHT):
    """1분 단위 값 리스트 → ASCII 라인차트. 좌측에 max(상단)·min(하단) 라벨."""
    vals = [v for v in vals if v is not None][-width:]
    if not vals:
        return "      |"
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    rows = [[" "] * len(vals) for _ in range(height)]
    for col, v in enumerate(vals):
        r = round((hi - v) / rng * (height - 1))   # hi→0행(상단), lo→마지막행(하단)
        rows[r][col] = "•"
    out = []
    for i, row in enumerate(rows):
        if i == 0:
            label = f"{hi:6.2f}"
        elif i == height - 1:
            label = f"{lo:6.2f}"
        else:
            label = " " * 6
        out.append(label + "|" + "".join(row))
    return "\n".join(out)


def build_message(data, prev_total, prev_bots, history):
    s = data["summary"]
    total = s.get("daily_ret")
    days = s.get("days")
    icon, arrow, delta = _trend(total, prev_total)
    head_days = f"{days}일" if days is not None else "—"
    tot_str = f"{total:+.2f}" if total is not None else "—"
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())   # 매 알림 첫 라인 = 시스템 시각
    lines = [ts,
             f"📊 전체 일평균수익률 ({head_days})",
             f"{tot_str}%/일  {icon}{delta:.2f}%{arrow}",
             "─" * 16]
    bots = sorted(data["bots"],
                  key=lambda b: (b.get("daily_ret") if b.get("daily_ret") is not None else -9999),
                  reverse=True)
    for b in bots:
        h = b.get("holding")
        mark = "?" if h is None else ("O" if h else "X")   # O=보유 X=미보유 ?=거래소미확인(ban 등)
        dr = b.get("daily_ret")
        dr = dr if dr is not None else 0.0
        pic, parrow, pdelta = _trend(dr, prev_bots.get(b["name"]))
        eb = b.get("entries_by_period") or {}
        ent1 = eb.get("1h", 0)   # 최근 1시간 진입 횟수
        ent4 = eb.get("4h", 0)   # 최근 4시간 진입 횟수
        orders = b.get("since_orders") or 0   # 누적 주문수(=청산 횟수)
        # 형식: ({1h진입}/1, {4h진입}/4, {누적주문수})
        lines.append(f"{mark} {b['name']}  {dr:+.2f}%  {pic}{pdelta:.2f}%{parrow}  ({ent1}/1, {ent4}/4, {orders:02d})")
    lines.append("")
    lines.append("최근 30분 전체 일평균 추이(%)")
    lines.append(ascii_chart(history))
    return "```\n" + "\n".join(lines) + "\n```"


def _post(content):
    url = _load_webhook()
    if not url:
        return False, "webhook URL 없음(discord_webhook.txt)"
    payload = json.dumps({"content": content, "username": USERNAME}).encode("utf-8")
    # 디스코드는 User-Agent 없는 요청을 403으로 거부 → 명시 필요
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "8888-monitor/1.0 (+discord-webhook)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return (r.status in (200, 204)), f"status={r.status}"
    except Exception as e:
        return False, str(e)[:150]


def tick(data):
    """집계 1건을 받아 직전값과 비교·발송하고 상태를 갱신. (ok, info) 반환."""
    prev_total, prev_bots, history = _load_state()
    total = data["summary"].get("daily_ret")
    history.append(total)
    history = history[-CHART_WIDTH:]
    msg = build_message(data, prev_total, prev_bots, history)
    ok, info = _post(msg)
    if ok:
        new_prev_bots = {b["name"]: (b.get("daily_ret") if b.get("daily_ret") is not None else 0.0)
                         for b in data["bots"]}
        _save_state(total, new_prev_bots, history)
    return ok, info


if __name__ == "__main__":
    # 단독 테스트: app.collect()로 현재 집계를 가져와 1건 발송
    import app
    ok, info = tick(app.collect())
    print(f"[DISCORD] 발송 {'성공' if ok else '실패'}: {info}")
