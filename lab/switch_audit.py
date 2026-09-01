"""
자동 매매방향 스위칭(5전 3패) 심층 점검.

engine.check_auto_mode_switch()가 쓰는 것과 **같은 경로**(history_helper)로 청산 이력을
읽어, 같은 필터·정렬·판정을 재현한다. 그 결과를 switch_state.json 기록·현재
USE_BLUEFROG와 대조해 '기준대로 작동했는가'를 가린다.

점검 항목
  ① USE_AUTO_MODE_SWITCH 활성 여부
  ② 청산 이력 파싱 결과 (필터: 청산완료 · exit_time 존재 · pnl≠0)
  ③ exit_time 정렬 안정성 — 코드가 문자열 정렬을 쓰므로 형식이 섞이면 순서가 깨진다
  ④ 지금 이 순간의 판정 (5전 패수 / 발동 여부 / 차단 사유)
  ⑤ switch_state.json 기록과의 정합
  ⑥ 스위칭 횟수와 현재 USE_BLUEFROG의 홀짝 정합

  python3 switch_audit.py [봇번호 ...]
"""
import json
import os
import sys

BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409", "8410"]


def load_closed(bot):
    """엔진과 동일한 경로·필터로 청산 거래를 만든다."""
    d = f"/Users/l/project/{bot}"
    saved, cwd = list(sys.path), os.getcwd()
    for m in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
        del sys.modules[m]
    try:
        os.chdir(d)
        sys.path.insert(0, d)
        from core.history_helper import load_local_trade_history, aggregate_and_pair_trades
        raw = load_local_trade_history()
        paired = aggregate_and_pair_trades(raw)
    finally:
        os.chdir(cwd)
        sys.path[:] = saved

    closed = [x for x in paired
              if x.get("status") == "청산 완료"
              and x.get("exit_time") is not None
              and round(float(x.get("pnl_usdt") or 0.0), 4) != 0.0]
    closed.sort(key=lambda x: str(x.get("exit_time")))
    return paired, closed


def audit(bot):
    d = f"/Users/l/project/{bot}"
    cfg = json.load(open(f"{d}/config.json"))
    issues, notes = [], []

    if not cfg.get("USE_AUTO_MODE_SWITCH"):
        notes.append("USE_AUTO_MODE_SWITCH=false (스위칭 비활성)")

    try:
        paired, closed = load_closed(bot)
    except Exception as e:
        return {"bot": bot, "issues": [f"이력 파싱 실패: {str(e)[:60]}"], "notes": notes}

    N = len(closed)
    notes.append(f"쌍맞춤 {len(paired)}건 → 판정대상 청산 {N}건")

    # ③ 정렬 안정성 — 문자열 정렬이므로 형식이 섞이면 시간순이 깨진다
    fmts = set()
    for x in closed:
        s = str(x.get("exit_time"))
        fmts.add(("T" in s[:11], len(s)))
    if len(fmts) > 1:
        issues.append(f"exit_time 형식이 {len(fmts)}종 혼재 — 문자열 정렬이 시간순과 어긋날 수 있음")

    # 실제로 시간순인지 파싱해 확인
    try:
        import pandas as pd
        ts = [pd.to_datetime(str(x.get("exit_time")), errors="coerce") for x in closed]
        if any(a is not None and b is not None and a > b
               for a, b in zip(ts, ts[1:]) if pd.notna(a) and pd.notna(b)):
            issues.append("정렬 결과가 실제 시간순과 불일치")
    except Exception:
        pass

    st = {}
    sf = f"{d}/data/switch_state.json"
    if os.path.exists(sf):
        try:
            st = json.load(open(sf))
        except Exception:
            issues.append("switch_state.json 파싱 불가")

    last_key = st.get("last_switched_key")
    last_cnt = st.get("last_switched_on_count", -1)

    # ④ 지금 판정
    verdict = "판정불가(청산 3건 미만)"
    if N >= 3:
        latest_key = str(closed[-1].get("exit_time") or closed[-1].get("timestamp"))
        if last_key == latest_key:
            verdict = "차단: 이 청산으로 이미 스위칭함"
        elif last_cnt != -1 and N >= last_cnt and (N - last_cnt) < 3:
            verdict = f"차단: 쿨다운(스위칭 후 {N-last_cnt}건 < 3건)"
        else:
            if N >= 5:
                r5 = closed[-5:]
                L = sum(1 for t in r5 if float(t.get("pnl_usdt") or 0.0) < 0.0)
                seq = "".join("x" if float(t.get("pnl_usdt") or 0.0) < 0.0 else "O" for t in r5)
                verdict = (f"**발동** 5전 {L}패 ({seq})" if L >= 3
                           else f"대기 5전 {L}패 ({seq}) — 3패 미만")
            else:
                l3 = closed[-3:]
                allx = all(float(t.get("pnl_usdt") or 0.0) < 0.0 for t in l3)
                seq = "".join("x" if float(t.get("pnl_usdt") or 0.0) < 0.0 else "O" for t in l3)
                verdict = f"**발동** 초기 3연패 ({seq})" if allx else f"대기 초기 {seq}"

    # 최근 10건 패턴
    tail = "".join("x" if float(t.get("pnl_usdt") or 0.0) < 0.0 else "O" for t in closed[-10:])

    # ⑥ 기록 정합
    if last_cnt != -1 and last_cnt > N:
        issues.append(f"기록된 스위칭 시점({last_cnt}건)이 현재 청산수({N})보다 큼 — 이력 초기화 흔적")

    return {"bot": bot, "N": N, "tail": tail, "verdict": verdict,
            "bluefrog": cfg.get("USE_BLUEFROG"), "st": st,
            "issues": issues, "notes": notes}


def main():
    bots = sys.argv[1:] or BOTS
    print("자동 매매방향 스위칭(5전 3패) 점검\n")
    bad = 0
    for b in bots:
        r = audit(b)
        head = "🔴" if r["issues"] else "🟢"
        if r["issues"]:
            bad += 1
        mode = "역(청개구리)" if r.get("bluefrog") else "순(정방향)"
        print(f"{head} {b}  현재모드 {mode}  청산 {r.get('N','?')}건")
        if r.get("tail"):
            print(f"     최근10: {r['tail']}")
        print(f"     판정: {r.get('verdict','?')}")
        st = r.get("st") or {}
        if st:
            print(f"     기록: {st.get('updated_at','?')} · {st.get('pattern','?')} "
                  f"· {str(st.get('reason',''))[:40]} (당시 {st.get('last_switched_on_count')}건)")
        else:
            print("     기록: 스위칭 이력 없음")
        for i in r["issues"]:
            print(f"     ✗ {i}")
        for n in r["notes"]:
            print(f"     · {n}")
        print()
    print(f"문제 있는 봇 {bad} / {len(bots)}")


if __name__ == "__main__":
    main()
