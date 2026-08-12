#!/usr/bin/env python3
"""daily_report.py — 4봇 테스트 일일 관찰 리포트 (거래소 원장 기준)

성과는 거래소가 말하는 값만 쓴다. 거래이력 CSV의 `수익(USDT)`는 초저가 코인에서
청산가 정밀도가 소실돼 부호가 뒤집힌다. 실측(2026-08-12 8403 BONK):
CSV가 청산가를 0.000002332 → 2e-06으로 잘라 기록해 손실 −$0.13이 이익 +$2.99가
됐고, 계좌의 10%인 $3.04 오차가 났다. 그 탓에 "+$2.26 수익"으로 보고했으나
실제로는 −$1.13 손실이었다.

로그(스캔·신호·게이트)는 CSV와 무관하므로 그대로 로그에서 센다.

판단 기준
  1) 진입 빈도 — 8408은 5분봉 시절 17건/일, 15분봉 전환 후 7.5건/일이 기준선.
  2) 게이트 통과율 — 백테스트 47%. 실거래가 크게 낮으면 스팬 재검토.
  3) 수수료 비중 — 실현손익 대비. 100%를 넘으면 '매매로 이기고 수수료로 지는' 상태.

수치만 내고 조치는 하지 않는다. 판단은 사람이 한다.
"""
import os
import re
import sys

sys.path.insert(0, "/Users/l/project/8888")
import exchange_pnl

BASE = "/Users/l/project"
BOTS = ["8401", "8403", "8408", "8409"]


def read_log(bot):
    """엔진 로그와 표준출력 로그를 합쳐 읽는다(봇마다 기록 위치가 갈린다).

    로그에 바이너리가 섞이면 grep이 파일을 통째로 건너뛰므로 파이썬으로 읽는다.
    실제로 그 탓에 '8408 신호 0건'으로 오보한 적이 있다(실제 106건).
    """
    out = []
    for name in ("bot_engine.log", "bot_stdout.log"):
        p = os.path.join(BASE, bot, name)
        if os.path.exists(p):
            try:
                out += open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                pass
    return out


def scan_stats(lines):
    scans = sigs = gate = order = 0
    for ln in lines:
        if "[SCAN] 완료" in ln:
            scans += 1
            m = re.search(r"신호 (\d+)개", ln)
            if m:
                sigs += int(m.group(1))
        elif "GATE BLOCK" in ln:
            gate += 1
        elif "ORDER RESULT" in ln and "결과: {" in ln:
            order += 1
    return scans, sigs, gate, order


def main():
    print("\n  ══ 4봇 관찰 리포트 (거래소 원장 기준) ══")
    print("  {:<6}{:>7}{:>7}{:>9}{:>7}{:>7}{:>11}{:>10}{:>9}{:>8}".format(
        "봇", "스캔", "신호", "게이트차단", "통과율", "진입",
        "실현손익", "총잔고", "시드대비", "수수료비"))
    print("  " + "─" * 82)
    hours = None
    ts = tr = tt = 0.0
    for b in BOTS:
        scans, sigs, gate, order = scan_stats(read_log(b))
        passed = sigs - gate
        rate = "{:.0f}%".format(100 * passed / sigs) if sigs else "―"
        x = exchange_pnl.get(b, max_age=30)
        if not x:
            print("  {:<6}{:>7}{:>7}{:>9}{:>7}{:>7}{:>11}".format(
                b, scans, sigs, gate, rate, order, "조회실패"))
            continue
        hours = hours or x["hours"]
        ret = (x["total"] - x["seed"]) / x["seed"] * 100 if x["seed"] else 0
        # 수수료 비중은 '이익 대비'라야 뜻이 있다. 손실이면 비교 대상이 없다.
        gross = x["real"] + x["fee"]
        fr = "{:.0f}%".format(100 * x["fee"] / gross) if gross > 0 else "―"
        ts += x["seed"]; tr += x["real"]; tt += x["total"]
        print("  {:<6}{:>7}{:>7}{:>9}{:>7}{:>7}{:>+11.4f}{:>10.2f}{:>+8.2f}%{:>8}".format(
            b, scans, sigs, gate, rate, order, x["real"], x["total"], ret, fr))
    print("  " + "─" * 82)
    if ts:
        print("  {:<6}{:>40}{:>+11.4f}{:>10.2f}{:>+8.2f}%".format(
            "합계", "", tr, tt, (tt - ts) / ts * 100))
    if hours:
        print("  경과 {:.1f}시간".format(hours))
    print("\n  기준선: 8408 진입 7.5건/일(15분봉) · 게이트 통과율 백테스트 47% ·"
          " 수수료비중 100%↑면 매매로 이기고 수수료로 지는 상태")


if __name__ == "__main__":
    main()
