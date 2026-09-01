"""
진입 가능 여부 전수 점검 — 무포지션이 '정상 대기'인지 '막혀 있음'인지 가른다.

주문을 내지 않고, 트레이더가 진입 전에 통과해야 하는 관문을 하나씩 실제 값으로 확인한다.
  ① 프로세스 생존 + 하트비트
  ② AUTO_TRADING
  ③ 잔고 하한 / 낙폭 가드
  ④ 글로벌·종목별 쿨다운, 연속 손절 차단
  ⑤ 포지션 상한 여유
  ⑥ 진입 증거금 × 레버리지 ≥ 거래소 최소 명목가
  ⑦ 거래소에 남은 고아 보호주문(진입 직후 청산을 유발)
  ⑧ 지금 이 순간 전략이 신호를 내는가 (종목별)

  python3 entry_readiness.py [봇번호 ...]
"""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime

BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409", "8410"]


def alive(bot):
    """cwd 기준으로 그 봇의 bot.py가 살아 있는지."""
    try:
        pids = subprocess.check_output(["pgrep", "-f", "bot.py"], text=True).split()
    except subprocess.CalledProcessError:
        return None
    for p in pids:
        try:
            out = subprocess.check_output(["lsof", "-a", "-p", p, "-d", "cwd", "-Fn"],
                                          text=True, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        for line in out.splitlines():
            if line.startswith("n") and line[1:] == f"/Users/l/project/{bot}":
                return int(p)
    return None


def jload(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default if default is not None else {}


async def probe(bot):
    d = f"/Users/l/project/{bot}"
    cfg_json = jload(f"{d}/config.json")
    stats = jload(f"{d}/data/stats.json")
    rt = jload(f"{d}/data/bot_runtime.json")
    pos_local = jload(f"{d}/data/active_positions.json")

    issues, notes = [], []

    # ① 프로세스 / 하트비트
    pid = alive(bot)
    if pid is None:
        issues.append("bot.py 미실행")
    hb = rt.get("last_heartbeat_epoch")
    if hb:
        age = datetime.now().timestamp() - float(hb)
        if age > 120:
            issues.append(f"하트비트 정지 {age/60:.0f}분")
        else:
            notes.append(f"하트비트 {age:.0f}초 전")
    else:
        notes.append("하트비트 기록 없음")

    # ② 자동매매
    if not cfg_json.get("AUTO_TRADING"):
        issues.append("AUTO_TRADING=false")

    # ③ 잔고 / 낙폭 가드
    saved, cwd = list(sys.path), os.getcwd()
    for m in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
        del sys.modules[m]
    bal = None
    min_cost = None
    orphan = None
    live_pos = None
    sigs = {}
    try:
        os.chdir(d)
        sys.path.insert(0, d)
        from dotenv import load_dotenv
        from core.api_keys import load_api_keys
        load_dotenv(override=True)
        load_api_keys(override=True)
        from core.config import CFG
        import core.exchange as EX

        Client = getattr(EX, "BinanceClient", None) or getattr(EX, "OKXClient", None)
        ex_id = str(getattr(CFG, "EXCHANGE_ID", "")).lower()
        pre = "BINANCE" if ex_id == "binance" else "OKX"
        c = Client(os.getenv(f"{pre}_API_KEY", ""), os.getenv(f"{pre}_SECRET_KEY", ""),
                   os.getenv(f"{pre}_PASSPHRASE", ""))
        if not await c.load_markets():
            issues.append("마켓 로드 실패(API)")
        else:
            try:
                b = await c.get_balance()
                bal = float(b.get("total") or 0)
            except Exception as e:
                issues.append(f"잔고 조회 실패: {str(e)[:40]}")
            try:
                ps = await c.get_positions()
                live_pos = [p["symbol"] for p in ps]
            except Exception:
                pass
            # 고아 보호주문
            if hasattr(c, "_fetch_algo_orders"):
                try:
                    algo = await c._fetch_algo_orders()
                    if algo is not None:
                        held = {(s or "").split("/")[0] for s in (live_pos or [])}
                        orphan = [o for o in algo
                                  if ((o.get("info", o).get("symbol") or "").replace("USDT", "")
                                      not in held)]
                except Exception:
                    pass
            # ⑥ 거래소가 요구하는 최소 명목가 (종목별 최댓값으로 보수적 판정)
            try:
                for _s in (list(cfg_json.get("SYMBOL_WHITELIST") or []) or
                           ["SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"]):
                    mk = c.exchange.market(_s)
                    mc = (mk.get("limits", {}).get("cost", {}) or {}).get("min")
                    for f in (mk.get("info", {}).get("filters") or []):
                        if f.get("filterType") == "MIN_NOTIONAL":
                            mc = float(f.get("notional") or mc or 0)
                    if mc:
                        min_cost = max(min_cost or 0.0, float(mc))
            except Exception:
                pass

            # ⑧ 현재 신호
            from core.strategy import StrategyEngine
            eng = (StrategyEngine(CFG)
                   if StrategyEngine.__init__.__code__.co_argcount > 1 else StrategyEngine())
            wl = list(cfg_json.get("SYMBOL_WHITELIST") or [])[:6]
            for s in wl:
                try:
                    df = await c.get_ohlcv(s, limit=300)
                    sg = eng.generate_signal(df.reset_index(), s)
                    sigs[s.split("/")[0]] = getattr(sg, "direction", "?")
                except Exception as e:
                    sigs[s.split("/")[0]] = f"오류:{str(e)[:20]}"
        await c.close()
    except Exception as e:
        issues.append(f"점검 예외: {str(e)[:60]}")
    finally:
        os.chdir(cwd)
        sys.path[:] = saved

    seed = float(stats.get("seed_money") or 0)
    if bal is not None:
        minb = float(cfg_json.get("MIN_REQUIRED_BALANCE_USDT", 1.0))
        if bal < minb:
            issues.append(f"잔고 부족 {bal:.2f} < {minb}")
        if seed > 0:
            dd = (seed - bal) / seed
            cap = float(cfg_json.get("MAX_DRAWDOWN_PCT", 0.3))
            if dd >= cap:
                issues.append(f"낙폭 가드 발동 {dd*100:.0f}% ≥ {cap*100:.0f}%")
            else:
                notes.append(f"낙폭 {dd*100:+.1f}%(한도 {cap*100:.0f}%)")

    # ④ 쿨다운
    g = stats.get("global_cooldown_until")
    if g:
        try:
            if datetime.fromisoformat(g) > datetime.now():
                issues.append(f"글로벌 쿨다운 {g[:16]}까지")
        except Exception:
            pass
    scd = stats.get("symbol_cooldown_until") or {}
    live_cd = []
    for s, iso in scd.items():
        try:
            if datetime.fromisoformat(iso) > datetime.now():
                live_cd.append(s.split("/")[0])
        except Exception:
            pass
    if live_cd:
        notes.append(f"종목 쿨다운 {','.join(live_cd)}")

    # ⑤ 포지션 상한
    cap_pos = int(cfg_json.get("MAX_POSITIONS", 3))
    n_live = len(live_pos) if live_pos is not None else len(pos_local)
    if n_live >= cap_pos:
        issues.append(f"포지션 상한 도달 {n_live}/{cap_pos}")

    # ⑥ 최소 명목가
    lev = float(cfg_json.get("LEVERAGE", 3))
    if cfg_json.get("USE_AUTO_COMPOUND") and bal:
        margin = bal * float(cfg_json.get("AUTO_COMPOUND_PCT", 20)) / 100.0
    else:
        margin = float(cfg_json.get("MARGIN_USDT", 2.0))
    notional = margin * lev
    notes.append(f"증거금 ${margin:.2f}×{lev:.0f} = 명목 ${notional:.2f}")
    # [2026-09-02] 최소 명목가는 거래소·종목마다 다르다. $5를 하드코딩하면
    # OKX(최소 명목가 없음, 최소 수량만 존재)를 오탐한다. 실제 한도로 비교한다.
    if min_cost and notional < min_cost:
        issues.append(f"명목가 ${notional:.2f} < 최소 ${min_cost:.0f}")

    # ⑦ 고아 주문
    if orphan:
        issues.append(f"고아 보호주문 {len(orphan)}건(진입 직후 청산 위험)")

    return {"bot": bot, "pid": pid, "bal": bal, "pos": n_live, "cap": cap_pos,
            "sigs": sigs, "issues": issues, "notes": notes}


async def main():
    bots = sys.argv[1:] or BOTS
    print("진입 가능 여부 점검 —", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    bad = 0
    for b in bots:
        r = await probe(b)
        head = "🔴" if r["issues"] else "🟢"
        if r["issues"]:
            bad += 1
        print(f"\n{head} {b}  PID {r['pid'] or '없음'} · 잔고 "
              f"{'$%.2f' % r['bal'] if r['bal'] is not None else '?'} · 포지션 {r['pos']}/{r['cap']}")
        for i in r["issues"]:
            print(f"     ✗ {i}")
        for n in r["notes"]:
            print(f"     · {n}")
        if r["sigs"]:
            print("     신호:", "  ".join(f"{k}={v}" for k, v in r["sigs"].items()))
        await asyncio.sleep(2)      # IP 레이트리밋 여유
    print(f"\n문제 있는 봇 {bad} / {len(bots)}")


if __name__ == "__main__":
    asyncio.run(main())
