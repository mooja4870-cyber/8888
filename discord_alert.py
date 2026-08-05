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

CHART_WIDTH = 40        # 최근 40포인트(=1분×40=40분)
CHART_HEIGHT = 6
USERNAME = "봇 관제"
EPS = 0.005             # 이 값 미만 변화는 '변화없음(⚪)'으로 간주


def _load_webhook():
    try:
        with open(WEBHOOK_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return s.get("prev_total"), s.get("prev_bots", {}), s.get("history", []), s.get("prev_sub_total")
    except (OSError, ValueError):
        return None, {}, [], None


def _save_state(path, prev_total, prev_bots, history, prev_sub_total=None):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"prev_total": prev_total, "prev_bots": prev_bots,
                   "history": history[-CHART_WIDTH:], "prev_sub_total": prev_sub_total}, f, ensure_ascii=False)
    os.replace(tmp, path)


def _trend(cur, prev):
    """(아이콘, 화살표, 변화량) — 직전값 대비. 수익=빨강 컨벤션: 상승=↑, 하락=↓."""
    if prev is None or cur is None or abs(cur - prev) < EPS:
        return "", "-", 0.0
    d = abs(cur - prev)
    return ("", "↑", d) if cur > prev else ("", "↓", d)


def ascii_chart(vals, width=CHART_WIDTH, height=CHART_HEIGHT):
    """1분 단위 값 리스트 → ASCII 라인차트."""
    vals = [v for v in vals if v is not None][-width:]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    rows = [[" "] * len(vals) for _ in range(height)]
    for col, v in enumerate(vals):
        r = round((hi - v) / rng * (height - 1))   # hi→0행(상단), lo→마지막행(하단)
        rows[r][col] = "•"
    out = ["".join(row) for row in rows]
    return "\n".join(out)


def get_bot_40min_history(b_obj):
    import app, time
    bid = b_obj.get("name", "")
    folder = b_obj.get("folder") or bid
    seed = b_obj.get("seed") or 10.0
    perf_str = b_obj.get("perf_start", "")
    
    path = f"/Users/l/project/{folder}/data/trade_history.csv"
    if not os.path.exists(path):
        return [(b_obj.get("daily_ret", 0.0) or 0.0)] * CHART_WIDTH

    exits = app._load_exits(path)
    perf_ts = None
    if perf_str:
        try:
            import send_discord_hourly_graph
            perf_ts = send_discord_hourly_graph.epoch(perf_str)
            exits = [e for e in exits if e[0] >= perf_str.replace("T", " ")[:19]]
        except Exception:
            pass

    now = time.time()
    history = []
    for i in range(CHART_WIDTH):
        T = now - 60 * (CHART_WIDTH - 1 - i)
        t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T))
        cum = sum(pnl for ts, pnl, oid in exits if ts <= t_str)
        cum_ret = (cum / seed) * 100.0 if seed else 0.0
        days = max(1.0, (T - perf_ts) / 86400.0) if perf_ts else 1.0
        d_ret = round(cum_ret / days, 2)
        history.append(d_ret)
        
    return history


def build_message(data, prev_total, prev_bots, history, title_prefix="전체", sub_assets=None, sub_total=None, prev_sub_total=None, include_bot_charts=False):
    s = data["summary"]
    total = s.get("daily_ret")
    days = s.get("days")
    icon, arrow, delta = _trend(total, prev_total)
    head_days = f"{days}일" if days is not None else "—"
    tot_str = f"{total:+.2f}" if total is not None else "—"
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())   # 매 알림 첫 라인 = 시스템 시각
    assets = s.get("assets")
    asset_str = f"[{assets:.2f}] " if assets is not None else ""   # 전체 일평균 줄 앞에 총자산 금액
    
    bots = sorted(data["bots"], key=lambda b: b.get("name", ""))
    bots_str = f" [{len(bots)}봇]" if len(bots) != 1 else ""
    
    lines = [ts,
             f"📊 {title_prefix} 일평균수익률 ({head_days}){bots_str}",
             f"{asset_str}{tot_str}% {icon}{delta:.2f}%{arrow}",
             "─" * 38,
             "승패 O/x : 왼쪽=과거 → 오른쪽=최신"]
    bots = sorted(data["bots"], key=lambda b: b.get("name", ""))
    for b in bots:
        dr = b.get("daily_ret")
        dr = dr if dr is not None else 0.0
        pic, parrow, pdelta = _trend(dr, prev_bots.get(b["name"]))
        eb = b.get("entries_by_period") or {}
        ent1 = eb.get("1h", 0)   # 최근 1시간 진입 횟수
        ent4 = eb.get("4h", 0)   # 최근 4시간 진입 횟수
        ent12 = eb.get("12h", 0) # 최근 12시간 진입 횟수
        ent24 = eb.get("24h", 0) # 최근 24시간 진입 횟수
        orders = b.get("since_orders") or 0   # 누적 주문수(=청산 횟수)
        sw = b.get("since_w") or 0
        sl = b.get("since_l") or 0
        # 형식: {롱포지션수}/{숏포지션수} {봇이름}  {일평균}%  {추이}  ({1h진입}, {4h진입}, {승/패})
        pos_long = b.get("ex_poslong")
        pos_short = b.get("ex_posshort")
        if pos_long is None or pos_short is None:
            if b.get("positions"):
                pos_str = f"{len(b['positions'])}/0"
            elif b.get("holding"):
                pos_str = "1/0"
            else:
                pos_str = "?/?"
        else:
            pos_str = f"{pos_long}/{pos_short}"
        
        b_name_short = b['name']
        b_days = b.get('days', 1.0)
        

        raw_seq = (b.get("seq", "") or "")[:30]
        seq_grouped = " ".join([raw_seq[i:i+5] for i in range(0, len(raw_seq), 5)])
        seq_str = f" {seq_grouped}" if seq_grouped else ""
        sun20 = b.get("sun20", 0)
        yeok20 = b.get("yeok20", 0)
        
        is_bf = bool(b.get("config", {}).get("USE_BLUEFROG", False)) if isinstance(b.get("config"), dict) else False
        mode_prefix = "역 " if is_bf else "순 "
        b_asset = b.get("ex_balance") if b.get("ex_balance") is not None else (b.get("balance") if b.get("balance") is not None else b.get("seed", 0.0))
        asset_val_str = f"${b_asset:.2f}" if b_asset is not None else "$0.00"
        lines.append(f"{mode_prefix}{pos_str} {b_name_short}  {b_days:.1f}  {asset_val_str}  {dr:+.2f}%  {pic}{pdelta:.2f}%{parrow}")
        lines.append(f"  ({ent1:02d}/{ent4:02d}|{ent12:02d}/{ent24:02d} {sw:02d}W/{sl:02d}L : 순{sun20}+역{yeok20})")
        if seq_str:
            lines.append(f"  {seq_str}")
        
        # 🤖 5분 정각 알림(include_bot_charts=True)일 때 개별 봇 40분 파동 차트 렌더링
        if include_bot_charts:
            bot_chart_hist = get_bot_40min_history(b)
            lines.append("─" * 38)
            lines.append("최근 40분 전체 일평균 추이(%)")
            lines.append(ascii_chart(bot_chart_hist))
            lines.append("")
        
    if not include_bot_charts:
        lines.append("─" * 38)
        lines.append("최근 40분 전체 일평균 추이(%)")
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


def recalc_data(data, exclude_names):
    import copy
    d = copy.deepcopy(data)
    bots = [b for b in d["bots"] if b["name"] not in exclude_names]
    d["bots"] = bots
    
    assets = 0.0
    seed = 0.0
    for b in bots:
        bal = b["ex_balance"] if (b.get("ex_ok") and b.get("ex_balance") is not None) else ((b.get("seed") or 0) + (b.get("total") or 0))
        bseed = b.get("seed") if b.get("seed") else bal
        assets += bal
        seed += bseed
        
    days = d["summary"].get("days", 1.0)
    cum_ret = round((assets - seed) / seed * 100, 2) if seed else None
    d["summary"]["assets"] = round(assets, 2)
    d["summary"]["cum_ret"] = cum_ret
    d["summary"]["cum_delta"] = round(assets - seed, 2)
    d["summary"]["daily_ret"] = round(cum_ret / days, 2) if cum_ret is not None else None
    return d


def _process_single(data, path, title_prefix, include_bot_charts=False):
    prev_total, prev_bots, history, prev_sub_total = _load_state(path)
    total = data["summary"].get("daily_ret")
    history.append(total)
    history = history[-CHART_WIDTH:]
    
    msg = build_message(data, prev_total, prev_bots, history, title_prefix, include_bot_charts=include_bot_charts)
    ok, info = _post(msg)
    if ok:
        new_prev_bots = {b["name"]: (b.get("daily_ret") if b.get("daily_ret") is not None else 0.0)
                         for b in data["bots"]}
        _save_state(path, total, new_prev_bots, history)
    return ok, info


def _process_subset(data, target_names, state_suffix, title_prefix, include_bot_charts=False):
    import copy
    import app
    d_sub = copy.deepcopy(data)
    d_sub["bots"] = [b for b in d_sub.get("bots", []) if str(b.get("name")) in target_names]
    if not d_sub["bots"]:
        return False, "No target bots found"
        
    if include_bot_charts:
        # 매 5분 정각 알림: 봇별 개별 메시지로 분할 발송 (디스코드 2000자 제한 완벽 회피 & 봇별 파동 차트 단독 렌더링)
        results = []
        for b_item in d_sub["bots"]:
            d_single = copy.deepcopy(d_sub)
            d_single["bots"] = [b_item]
            d_single["summary"]["assets"] = b_item.get("ex_balance") or b_item.get("seed") or 0.0
            d_single["summary"]["daily_ret"] = b_item.get("daily_ret") or 0.0
            d_single["summary"]["days"] = b_item.get("days", 1.0)
            
            b_name = b_item.get("name")
            state_file = STATE_FILE.replace(".json", f"_{b_name}.json")
            ok, info = _process_single(d_single, state_file, f" [{b_name} 봇]", include_bot_charts=True)
            results.append(ok)
            time.sleep(0.5)   # 웹훅 레이트리밋 방지
        return any(results), f"5Min Per-Bot Split Sent ({len(results)} bots)"
    else:
        # 매 1분 실시간 알림: 기존 깔끔 그룹 메시지
        assets = 0.0
        seed = 0.0
        for b in d_sub["bots"]:
            bal = b.get("ex_balance") if (b.get("ex_ok") and b.get("ex_balance") is not None) else ((b.get("seed") or 0) + (b.get("total") or 0))
            bseed = b.get("seed") if b.get("seed") else bal
            assets += bal
            seed += bseed
            
        days = max([app.bot_days(b["perf_start"]) for b in d_sub["bots"]] or [1.0])
        cum_ret = round((assets - seed) / seed * 100, 2) if seed else None
        
        valid_bots = [b for b in d_sub["bots"] if b.get("daily_ret") is not None and b.get("seed")]
        if valid_bots:
            tot_s = sum(b["seed"] for b in valid_bots)
            avg_daily = round(sum(b["daily_ret"] * b["seed"] for b in valid_bots) / tot_s, 2) if tot_s else 0.0
        else:
            avg_daily = round(cum_ret / days, 2) if cum_ret is not None else None
            
        d_sub["summary"]["assets"] = round(assets, 2)
        d_sub["summary"]["cum_ret"] = cum_ret
        d_sub["summary"]["cum_delta"] = round(assets - seed, 2)
        d_sub["summary"]["daily_ret"] = avg_daily
        d_sub["summary"]["days"] = round(days, 1)
        
        state_file = STATE_FILE.replace(".json", state_suffix)
        return _process_single(d_sub, state_file, title_prefix, include_bot_charts=False)


def tick(data, tick_count=0, include_bot_charts=False):
    """집계 1건을 받아 매 1분마다 2개 봇 그룹(그룹 1: 2,4,5,7,9 / 그룹 2: 1,3,8)으로 나누어 디스코드 알림 발송 및 상태 갱신."""
    group_1_names = {"8402", "8404", "8405", "8407", "8409"}
    group_2_names = {"8401", "8403", "8408"}
    
    # 실제 data.get("bots")에 존재하는 봇만 필터링
    actual_1 = {str(b.get("name")) for b in data.get("bots", []) if str(b.get("name")) in group_1_names}
    actual_2 = {str(b.get("name")) for b in data.get("bots", []) if str(b.get("name")) in group_2_names}

    ok1, info1 = False, "No bots in Group 1"
    if actual_1:
        ok1, info1 = _process_subset(data, actual_1, "_group_1.json", "1그룹(8402,4,5,7,9) 전체", include_bot_charts=False)

    ok2, info2 = False, "No bots in Group 2"
    if actual_2:
        ok2, info2 = _process_subset(data, actual_2, "_group_2.json", "2그룹(8401,3,8) 전체", include_bot_charts=False)

    return (ok1 or ok2), f"Group 1({len(actual_1)}): {info1} | Group 2({len(actual_2)}): {info2}"


if __name__ == "__main__":
    # 단독 테스트: app.collect()로 현재 집계를 가져와 발송
    import app
    ok, info = tick(app.collect())
    print(f"[DISCORD] 발송 {'성공' if ok else '실패'}: {info}")
