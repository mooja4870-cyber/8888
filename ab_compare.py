#!/usr/bin/env python3
"""ab_compare.py — 세력흔적 3봇 A/B/C 짝지어 비교

설계
────
세 봇은 **진입 조건이 완전히 같다**(Sniper15, 같은 OKX 상위 80종목, 15분봉, 롱 전용).
다른 것은 청산 처리 한 가지씩이다.

  · 8401 (기준) — +5% 절반 익절 · 마지노선 추종(샹들리에 K=1.96)
  · 8402 (B)   — **익절 없음** (나머지는 8401과 동일)
  · 8404 (C)   — **마지노선 추종 없음** (진입 시점 손절 고정, 나머지 동일)

**같은 종목·비슷한 시각에 들어간 거래끼리 짝을 지어** 비교한다. 짝 비교를 하면
시장 등락이 상쇄되고 처리 방식의 차이만 남아, 필요한 표본이 10분의 1로 줄어든다.
이 프로젝트에서 "며칠로는 판단 불가"였던 이유가 짝이 아닌 비교를 했기 때문이다.

무엇을 검증하나
  8402 — 문서의 "+5% 절반 익절"이 옳은가.
         이 프로젝트에서 '조기 청산하지 마라'는 여섯 번 확인됐다. 여기서도 그런가.
  8404 — 문서 원칙4의 "마지노선"이 **따라 올라가는 선**인가 **진입 시점 고정선**인가.
         문서가 말하지 않아 추종으로 해석해 구현했다. 근거가 없었다.

손익은 **거래소 원장만** 쓴다. trade_history.csv는 12배 어긋난 실측이 있고,
거래소가 자동 청산한 건은 아예 기록되지도 않는다("오프라인 청산 감지 → 상태 삭제").

사용
    python3 ab_compare.py                      # 기본 기준시각부터
    python3 ab_compare.py "2026-08-21 23:33:00"
"""
import json
import math
import os
import subprocess
import sys

BASE = "/Users/l/project"
REF = "8401"                                  # 기준봇
CMP = [("8402", "익절없음"), ("8404", "추종없음")]
START = "2026-08-21 23:33:00"                 # 3봇 공통 시작 시각
PAIR_WINDOW_H = 6                             # 같은 종목이 이 시간 안에 청산되면 같은 국면


def ledger(bot, since_str):
    """거래소 원장에서 (종목, 실현손익, 청산시각ms) 목록."""
    code = f'SINCE = {since_str!r}\n' + '''
import asyncio, os, sys, time, json
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from core.api_keys import load_api_keys; load_api_keys(override=True)
async def m():
    from core.exchange import OKXClient as C
    cl = C(os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), os.getenv("OKX_PASSPHRASE",""))
    await cl.load_markets(); ex = cl.exchange
    since = int(time.mktime(time.strptime(SINCE, "%Y-%m-%d %H:%M:%S")) * 1000)
    # [2026-08-24] 100건 한도 제거 — 회전이 빠른 봇은 오래된 쪽이 통째로 잘린다
    _seen, _after = {}, None
    for _ in range(60):
        _pr = {"instType":"SWAP","limit":"100"}
        if _after: _pr["after"] = str(_after)
        _rr = await ex.privateGetAccountPositionsHistory(_pr)
        _dd = _rr.get("data") or []
        if not _dd: break
        for _x in _dd:
            _seen[(_x.get("posId"), _x.get("uTime"), _x.get("instId"))] = _x
        _old = min(int(_x.get("uTime") or 0) for _x in _dd)
        if len(_dd) < 100 or _old < since: break
        _after = _old
    r = {"data": list(_seen.values())}
    out = []
    for x in (r.get("data") or []):
        t = int(x.get("uTime") or 0)
        if t >= since:
            out.append([x.get("instId",""), float(x.get("realizedPnl") or 0), t])
    print("JSON" + json.dumps(out))
    await ex.close()
asyncio.run(m())
'''
    py = os.path.join(BASE, bot, "venv", "bin", "python3")
    try:
        r = subprocess.run([py, "-c", code], cwd=os.path.join(BASE, bot),
                           capture_output=True, text=True, timeout=180)
    except Exception:
        return []
    for line in (r.stdout or "").splitlines():
        if line.startswith("JSON"):
            try:
                return json.loads(line[4:])
            except ValueError:
                return []
    return []


def stat(v):
    n = len(v)
    if n < 2:
        return None
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5
    se = sd / math.sqrt(n)
    return {"n": n, "mean": m, "sd": sd, "se": se, "sigma": m / se if se > 0 else 0}


def pair(la, lb):
    """같은 종목·PAIR_WINDOW_H 이내 청산끼리 1:1로 묶는다."""
    used, out = set(), []
    for sym, pa, ta in la:
        best, bi = None, None
        for i, (sb, pb, tb) in enumerate(lb):
            if i in used or sb != sym:
                continue
            dt = abs(tb - ta) / 3600000.0
            if dt <= PAIR_WINDOW_H and (best is None or dt < best):
                best, bi = dt, i
        if bi is not None:
            used.add(bi)
            out.append((sym, pa, lb[bi][1]))
    return out


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else START
    print(f"  세력흔적 A/B/C — 기준 {REF} · 기준시각 {since} 이후 · 거래소 원장\n")

    led = {REF: ledger(REF, since)}
    for b, _ in CMP:
        led[b] = ledger(b, since)
    for b in led:
        print(f"    {b}: 청산 {len(led[b])}건")
    print()

    if not led[REF]:
        print("  → 기준봇 표본이 없습니다. 거래가 쌓인 뒤 다시 실행하십시오.")
        return

    for b, label in CMP:
        print(f"  ■ {REF}(기준) vs {b}({label})")
        if not led[b]:
            print("    표본 없음\n")
            continue
        pairs = pair(led[REF], led[b])
        if len(pairs) < 2:
            print(f"    짝 {len(pairs)}쌍 — 부족\n")
            continue
        diffs = [pb - pa for _, pa, pb in pairs]
        s = stat(diffs)
        print(f"    짝 {len(pairs)}쌍 · {b}−{REF} 건당 {s['mean']:+.4f} USDT ± {s['se']:.4f} ({s['sigma']:+.1f}σ)")
        print(f"    합계  {REF} {sum(p[1] for p in pairs):+.4f} · {b} {sum(p[2] for p in pairs):+.4f}")
        if abs(s["sigma"]) >= 2:
            print(f"    → **{b if s['mean'] > 0 else REF} 우세** (2σ 통과)")
        else:
            if s["mean"]:
                need = int((2 * s["sd"] / abs(s["mean"])) ** 2)
                print(f"    → 판정 불가. 2σ까지 약 {max(0, need - s['n'])}쌍 더 필요")
            else:
                print("    → 판정 불가 (차이 0)")
        for sym, pa, pb in sorted(pairs, key=lambda x: x[2] - x[1])[:8]:
            print(f"      {sym:<20} {REF} {pa:+.4f}  {b} {pb:+.4f}  차이 {pb-pa:+.4f}")
        print()

    print("  ■ 전체 평균 (참고 — 짝이 아니라 잡음이 큼)")
    for b in [REF] + [x[0] for x in CMP]:
        s = stat([x[1] for x in led[b]])
        if s:
            print(f"    {b}  {s['n']}건 건당 {s['mean']:+.4f} ± {s['se']:.4f}")


if __name__ == "__main__":
    main()
