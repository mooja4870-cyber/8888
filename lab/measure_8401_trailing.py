#!/usr/bin/env python3
"""measure_8401_trailing.py — 8401 트레일링 완화 효과 측정

무엇을 바꿨나 (2026-08-25 15:47 KST)
──────────────────────────────────
  TRAILING_ACTIVATE_PCT  0.80% → 1.50%
  TRAILING_CALLBACK_PCT  0.30% → 1.20%   (core/config.py 설계 기본값으로 복원)

왜 바꿨나 — 변경 전 원장 213건 실측:
  · 이익거래 81건 중 51%가 +1~3%에 몰려 중앙값 +1.43%
  · 최대 +7.14%, 그 위는 단 1건 → 오른쪽 꼬리가 잘려 있었다
  · 그런데 상위 5건이 매매이익의 333%를 만든다 = 대박 꼬리가 수익원이다
  · trailing_stop_manager.py:506의 콜백 사다리가 거꾸로였다
    (정상 0.30% / 약세1단 1.0% / 2단 0.7% / 3단 0.4% — 정상이 가장 좁음)

무엇을 볼 것인가 — 콜백을 넓혔으니 **이익 분포의 오른쪽 꼬리**가 자라야 한다.
  ① 이익거래 중앙값 상승 (기준 +1.43%)
  ② +7% 초과 거래 출현 (기준 213건 중 1건)
  ③ 건당 매매손익(수수료 전) 상승 (기준 +5.2bp)
  ④ 건당 순손익 (기준 −4.8bp) — 이게 0을 넘어야 흑자다

⚠️ 판정 주의
  변경 전 t값이 +0.28에 불과했다. 213건으로는 엣지 유무조차 가릴 수 없다는 뜻이다.
  변동성이 큰 꼬리분포라 **수백 건이 쌓이기 전에는 어떤 결론도 내리지 말 것.**
  이 스크립트는 t값과 필요 표본수를 함께 찍어 성급한 판정을 막는다.

사용법:  python3 lab/measure_8401_trailing.py
"""
import math
import os
import subprocess
import sys
import time

import numpy as np

BOT = "8401"
BASE = "/Users/l/project"
CUTOFF = "2026-08-25 15:47:00"          # 트레일링 변경 시각
SINCE = "2026-08-20 13:13:24"           # 측정 시작(perf_start)
TAKER_ROUNDTRIP = 0.000998              # 실측 왕복 수수료율


def ledger(since_str):
    code = f'SINCE_S = {since_str!r}\n' + '''
import asyncio, os, sys, time, json
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from core.api_keys import load_api_keys; load_api_keys(override=True)
async def m():
    from core.exchange import OKXClient as C
    cl = C(os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), os.getenv("OKX_PASSPHRASE",""))
    await cl.load_markets(); ex = cl.exchange
    since = int(time.mktime(time.strptime(SINCE_S, "%Y-%m-%d %H:%M:%S")) * 1000)
    seen, after = {}, None
    for _ in range(60):
        pr = {"instType":"SWAP","limit":"100"}
        if after: pr["after"] = str(after)
        rr = await ex.privateGetAccountPositionsHistory(pr)
        dd = rr.get("data") or []
        if not dd: break
        for x in dd: seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x
        oldest = min(int(x.get("uTime") or 0) for x in dd)
        if len(dd) < 100 or oldest < since: break
        after = oldest
    out = []
    for x in seen.values():
        if int(x.get("uTime") or 0) < since: continue
        op = float(x.get("openAvgPx") or 0); cp = float(x.get("closeAvgPx") or 0)
        out.append([int(x.get("cTime") or 0), int(x.get("uTime") or 0),
                    float(x.get("realizedPnl") or 0), float(x.get("fee") or 0),
                    float(x.get("fundingFee") or 0), op, cp])
    print("JSON" + json.dumps(out))
    await ex.close()
asyncio.run(m())
'''
    py = os.path.join(BASE, BOT, "venv", "bin", "python3")
    r = subprocess.run([py, "-c", code], cwd=os.path.join(BASE, BOT),
                       capture_output=True, text=True, timeout=300)
    import json
    for line in (r.stdout or "").splitlines():
        if line.startswith("JSON"):
            return json.loads(line[4:])
    return []


def stats(rows, label):
    if len(rows) < 3:
        print(f"  {label}: {len(rows)}건 — 아직 판단 불가")
        return None
    a = np.array(rows, dtype=float)
    net = a[:, 2]
    gross = a[:, 2] - a[:, 3] - a[:, 4]
    notl = np.abs(a[:, 3]) / TAKER_ROUNDTRIP
    ok = notl > 0
    bp_net = net[ok] / notl[ok] * 10000
    bp_gr = gross[ok] / notl[ok] * 10000
    pc = np.where(a[:, 5] > 0, (a[:, 6] - a[:, 5]) / np.maximum(a[:, 5], 1e-12) * 100, 0)
    win = pc[gross > 0]
    t = bp_net.mean() / (bp_net.std(ddof=1) / math.sqrt(len(bp_net))) if len(bp_net) > 1 else 0

    print(f"  {label}  ({len(rows)}건)")
    print(f"    건당 매매손익(수수료 전) {bp_gr.mean():+7.2f}bp")
    print(f"    건당 순손익             {bp_net.mean():+7.2f}bp   t={t:+.2f}")
    print(f"    승률                    {(gross > 0).mean()*100:5.1f}%")
    if len(win):
        print(f"    이익거래 가격변동 중앙값 {np.median(win):+6.2f}%  최대 {win.max():+6.2f}%")
        print(f"    +7% 초과 이익거래       {(win > 7).sum()}건 ({(win > 7).mean()*100:.1f}%)")
    return bp_net


def main():
    cut_ms = int(time.mktime(time.strptime(CUTOFF, "%Y-%m-%d %H:%M:%S")) * 1000)
    rows = ledger(SINCE)
    if not rows:
        print("  원장 조회 실패")
        return 1
    before = [r for r in rows if r[1] < cut_ms]     # 청산 시각 기준
    after = [r for r in rows if r[1] >= cut_ms]

    print(f"  ══ 8401 트레일링 완화 효과 (변경 {CUTOFF}) ══\n")
    b = stats(before, "변경 전 (콜백 0.30%)")
    print()
    a = stats(after, "변경 후 (콜백 1.20%)")

    print()
    if a is None or b is None or len(a) < 30:
        need = 0 if a is None else max(0, 30 - len(a))
        print(f"  → 판정 보류. 변경 후 표본이 최소 30건은 있어야 형태라도 본다"
              + (f" (앞으로 {need}건 더)" if a is not None else ""))
    else:
        d = a.mean() - b.mean()
        se = math.sqrt(a.var(ddof=1)/len(a) + b.var(ddof=1)/len(b))
        tt = d / se if se else 0
        print(f"  → 차이 {d:+.2f}bp · t={tt:+.2f}")
        print("     |t|<2 면 아직 '달라졌다'고 말할 수 없다. 표본을 더 쌓을 것.")
    print("\n  ⚠️ 변경 전조차 t=+0.28이었다. 이 전략은 소수 대박에 의존해 분산이 크므로")
    print("     수백 건 전에는 어떤 결론도 성급하다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
