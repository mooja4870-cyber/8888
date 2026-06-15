#!/usr/bin/env python3
"""snapshots.json 과거 backfill (1회성).
trade_history.csv 실현손익 기준으로 최근 24h의 :00·:30 시점 봇별 일평균수익률을 근사 복원한다.
- 근사 행은 approx=True로 표시(대시보드가 ≈ 마커로 구분).
- 라이브 기록기(record_snapshot)가 만든 실측 행은 보존하고 덮어쓰지 않는다(실측 > 근사).
- 봇 폴더는 읽기 전용. 결과는 8888/snapshots.json(gitignore).
사용: python3 backfill_snapshots.py
"""
import csv
import json
import os
import time

BASE = "/Users/l/project"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots.json")
KEEP = 48
BOTS = [("8401_okx", "8401"), ("8402_okx", "8402"), ("8403_okx", "8403"),
        ("8404_okx", "8404"), ("8405_okx", "8405"), ("8406_okx", "8406"),
        ("8407_bnc", "8407"), ("8408_bnc", "8408"), ("8409_bnc", "8409"),
        ("8501_bnc", "8501")]


def epoch(ts):
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def bot_hist(folder):
    """(seed, perf_epoch, [(exit_epoch, pnl), ...]) — stats.json + trade_history.csv."""
    d = os.path.join(BASE, folder, "data")
    seed = perf = None
    try:
        s = json.load(open(os.path.join(d, "stats.json"), encoding="utf-8"))
        seed = s.get("seed_money")
        perf = epoch(s.get("perf_start_time") or "")
    except Exception:
        pass
    exits = []
    try:
        with open(os.path.join(d, "trade_history.csv"), encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) < 7 or r[2] != "청산":
                    continue
                e = epoch(r[0].strip())
                if e is None:
                    continue
                try:
                    exits.append((e, float(r[6])))
                except Exception:
                    continue
    except Exception:
        pass
    exits.sort()
    return seed, perf, exits


def daily_ret_at(seed, perf, exits, T):
    """T 시점까지의 실현손익 누적으로 일평균수익률 근사. perf_start 이전이면 None."""
    if not seed or not perf or T < perf:
        return None
    cum = sum(p for e, p in exits if perf <= e <= T)
    cum_ret = cum / seed * 100
    days = max(1.0, (T - perf) / 86400)
    return round(cum_ret / days, 2)


def main():
    now = time.time()
    lt = time.localtime(now)
    sec_into = lt.tm_min * 60 + lt.tm_sec
    latest = int(now - (sec_into % 1800))          # now 이하 최신 :00/:30 경계
    bounds = [latest - 1800 * i for i in range(KEEP)]

    bots = [(name,) + bot_hist(folder) for folder, name in BOTS]
    rows = []
    for T in bounds:
        botmap = {name: daily_ret_at(seed, perf, exits, T)
                  for name, seed, perf, exits in bots}
        rows.append({"ts": time.strftime("%Y-%m-%d %H:%M", time.localtime(T)),
                     "t": time.strftime("%H:%M", time.localtime(T)),
                     "bots": botmap, "approx": True})

    try:
        existing = json.load(open(SNAP, encoding="utf-8"))
    except Exception:
        existing = []

    by_ts = {r["ts"]: r for r in rows}             # backfill(근사) 먼저
    for r in existing:                              # 실측이 덮어씀, off-grid(시드)는 버림
        if r["ts"][14:16] in ("00", "30"):
            by_ts[r["ts"]] = r
    merged = sorted(by_ts.values(), key=lambda r: r["ts"])[-KEEP:]

    tmp = SNAP + ".tmp"
    json.dump(merged, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, SNAP)
    ap = sum(1 for r in merged if r.get("approx"))
    print(f"backfill 완료: {len(merged)}행 (근사 {ap}, 실측 {len(merged) - ap})")


if __name__ == "__main__":
    main()
