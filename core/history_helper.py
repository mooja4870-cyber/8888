"""
매매 이력 파싱, 병합 및 진입/청산 페어링 헬퍼 모듈
"""
import os
import logging
import pandas as pd
from typing import List, Dict, Optional
import core.logger as logger_store
from core.config import CFG

logger = logging.getLogger(__name__)

CSV_COLUMNS = {
    "timestamp": "시간",
    "symbol": "심볼",
    "category": "유형",
    "side": "방향",
    "price": "가격",
    "amount": "수량",
    "pnl": "수익(USDT)",
    "pnl_pct": "수익률(%)",
    "exit_type": "청산유형",
    "is_ts": "T/S",
    "leverage": "레버리지",
    "order_id": "주문ID",
    "trade_id": "체결ID",
    "fee": "수수료(USDT)",
    "trade_mode": "매매모드",
}


def _normalize_id(value) -> str:
    """CSV/거래소에서 온 주문·체결 ID를 비교 가능한 문자열로 정규화."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in ("", "nan", "none"):
        return ""
    if text.startswith("ID_"):
        text = text[3:]
    try:
        num = float(text)
        if num.is_integer():
            return str(int(num))
    except (TypeError, ValueError):
        pass
    return text


def _trade_dedupe_key(trade: Dict):
    trade_id = _normalize_id(trade.get("trade_id"))
    if trade_id:
        return ("trade_id", trade.get("symbol"), trade_id)

    timestamp = trade.get("timestamp")
    if hasattr(timestamp, "strftime"):
        timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "fallback",
        timestamp,
        trade.get("symbol"),
        str(trade.get("side", "")).lower(),
        round(float(trade.get("price") or 0), 12),
        round(float(trade.get("amount") or 0), 12),
        round(float(trade.get("pnl") or 0), 12),
        _normalize_id(trade.get("order_id")),
    )


def _atomic_ids(trade: Dict) -> set:
    """체결ID를 '|' 단위로 분해해 낱개(atomic) 체결ID 집합 반환.
    합산본('a|b|c|d')과 낱개('a')를 동일 레벨에서 비교하기 위함."""
    raw = trade.get("trade_id")
    if raw is None:
        return set()
    out = set()
    for piece in str(raw).split("|"):
        nid = _normalize_id(piece)
        if nid:
            out.add(nid)
    return out


def _dedupe_trades(trades: List[Dict]) -> List[Dict]:
    """atomic 체결ID 기반 중복 제거.
    - 실제 체결ID가 존재하는 동일 주문ID(order_id)의 경우, 체결ID가 없는 임시 요약 기록은 중복 진입 합산 방지를 위해 제외.
    - 합산본('a|b|c|d') 또는 낱개('a')가 이미 등장한 체결을 포함하면 중복으로 간주해 제거.
    - 체결ID가 없는 레코드는 기존 fallback 키로 중복 제거.
    => 청산 이중기록(트레이더 합산본 + Reconciler 낱개)으로 인한 '진입유실' 및 진입 수량 중복합산 방지."""
    # [진입유실 근본수정] 구분(진입/청산)까지 일치하는 실측 체결이 있을 때만 임시행을 중복으로 본다.
    valid_order_keys = {
        (t.get("order_id"), str(t.get("category", "")).strip())
        for t in trades
        if t.get("trade_id") and t.get("order_id")
    }

    seen_keys = set()
    seen_atomic = set()
    out = []
    for t in trades:
        # 실제 체결 이력이 존재하는 주문의 임시 기록(체결ID 없음)은 중복 진입 수량 합산을 막기 위해 제외
        if not t.get("trade_id") and (t.get("order_id"), str(t.get("category", "")).strip()) in valid_order_keys:
            logger.debug(
                "[DEDUPE] 체결ID가 존재하는 주문의 임시 요약 기록 제거: %s %s orderID=%s",
                t.get("symbol"), t.get("category"), t.get("order_id")
            )
            continue

        atoms = _atomic_ids(t)
        if atoms:
            dup = atoms & seen_atomic
            if dup:
                logger.warning(
                    "[DEDUPE] 중복 청산/체결 제거: %s %s 체결ID겹침=%s",
                    t.get("symbol"), t.get("category"), sorted(dup)
                )
                continue
            seen_atomic |= atoms
            out.append(t)
        else:
            key = _trade_dedupe_key(t)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(t)
    return out


def _row_to_trade(row) -> Optional[Dict]:
    try:
        order_id = _normalize_id(row.get(CSV_COLUMNS.get("order_id", "주문ID"), ""))
        if "MOCK" in order_id or order_id == "":
            return None

        pnl_val = row.get(CSV_COLUMNS.get("pnl", "수익(USDT)"), 0.0)
        pnl = 0.0 if pd.isna(pnl_val) else float(pnl_val)

        pnl_pct_val = row.get(CSV_COLUMNS.get("pnl_pct", "수익률(%)"), 0.0)
        pnl_pct = 0.0 if pd.isna(pnl_pct_val) else float(pnl_pct_val)

        lev_val = row.get(CSV_COLUMNS.get("leverage", "레버리지"))
        exit_type_col = CSV_COLUMNS.get("exit_type", "청산유형")
        exit_type_val = row.get(exit_type_col, "")
        legacy_ts_val = row.get(CSV_COLUMNS.get("is_ts", "T/S"), "")
        exit_type = "" if pd.isna(exit_type_val) else str(exit_type_val).strip()
        legacy_ts = "" if pd.isna(legacy_ts_val) else str(legacy_ts_val).strip()
        if not exit_type and legacy_ts:
            exit_type = "T/S" if legacy_ts in ("✅", "Y", "1", "True", "true", "T/S") else legacy_ts

        # If order_id or trade_id was shifted into lev_val, try to recover or ignore
        if str(lev_val).startswith("ID_"):
            # This means the columns were shifted left by 1 because T/S is missing.
            # We can recover order_id and trade_id from the shifted columns.
            order_id = _normalize_id(lev_val)
            trade_id_val = row.get(CSV_COLUMNS.get("order_id", "주문ID"), "")
            trade_id = _normalize_id(trade_id_val)
            # 구버전 CSV에서 청산유형(T/S) 컬럼이 없을 때 발생한 시프트 복구
            try:
                leverage = CFG.LEVERAGE if pd.isna(legacy_ts_val) or str(legacy_ts_val).strip() == "" else int(float(legacy_ts_val))
            except ValueError:
                leverage = CFG.LEVERAGE
            exit_type = ""
        else:
            trade_id_val = row.get(CSV_COLUMNS.get("trade_id", "체결ID"), "")
            trade_id = _normalize_id(trade_id_val)
            try:
                leverage = CFG.LEVERAGE if pd.isna(lev_val) or str(lev_val).strip() == "" else int(float(lev_val))
            except ValueError:
                leverage = CFG.LEVERAGE

        category = str(row[CSV_COLUMNS["category"]])
        amount = float(row[CSV_COLUMNS["amount"]])
        
        fee_col = CSV_COLUMNS.get("fee", "수수료(USDT)")
        fee_val = row.get(fee_col, 0.0)
        fee = 0.0 if pd.isna(fee_val) or str(fee_val).strip() == "" else float(fee_val)

        mode_col = CSV_COLUMNS.get("trade_mode", "매매모드")
        mode_val = row.get(mode_col, "")
        if pd.isna(mode_val) or not str(mode_val).strip():
            # [v9.9.3] CSV에 매매모드가 없는 구(舊) 행을 현재 모드로 채우지 않는다(이력 왜곡).
            mode_val = ""
        else:
            mode_val = str(mode_val).strip()

        return {
            "timestamp": pd.to_datetime(row[CSV_COLUMNS["timestamp"]]),
            "symbol": str(row[CSV_COLUMNS["symbol"]]),
            "category": category,
            "side": str(row[CSV_COLUMNS["side"]]),
            "price": float(row[CSV_COLUMNS["price"]]),
            "amount": amount,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_type": exit_type,
            "trade_mode": mode_val,
            "leverage": leverage,
            "order_id": order_id,
            "trade_id": trade_id,
            "fee": fee,
        }
    except Exception as e:
        # If row is completely malformed, skip it
        return None


def get_position_direction(category: str, side: str) -> str:
    """유형(진입/청산)과 방향(buy/sell/long/short) 조합으로 포지션 방향 판별"""
    cat = category.strip()
    s = side.strip().lower()
    
    # 만약 방향 자체가 long/short으로 명시되어 있다면 직접 반환
    if s in ("long", "l"):
        return "LONG"
    if s in ("short", "s"):
        return "SHORT"
    
    # buy/sell인 경우 유형(진입/청산) 기준으로 판별
    if cat in ("진입", "*진입"):
        return "LONG" if s == "buy" else "SHORT"
    else:  # 청산
        # 롱 포지션 청산은 매도(sell), 숏 포지션 청산은 매수(buy)
        return "LONG" if s == "sell" else "SHORT"

def load_local_trade_history() -> List[Dict]:
    """local trade_history.csv 로드하여 원본 데이터 리스트 반환 (모의 거래 필터링 포함)"""
    if not os.path.exists(logger_store.LOG_FILE):
        return []
    try:
        df = pd.read_csv(logger_store.LOG_FILE, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        
        trades = []
        for _, row in df.iterrows():
            trade = _row_to_trade(row)
            if trade is None:
                continue
            trades.append(trade)
        return _dedupe_trades(trades)
    except Exception as e:
        print(f"[HISTORY_HELPER] 로컬 CSV 로드 실패: {e}")
        return []


def compact_local_trade_history() -> int:
    """trade_history.csv의 중복 행 및 체결ID 없는 임시 기록(Placeholder)을 제거합니다."""
    path = logger_store.LOG_FILE
    if not os.path.exists(path):
        return 0

    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
    except Exception as e:
        print(f"[HISTORY_HELPER] CSV 로드 실패 (compact): {e}")
        return 0

    # 1단계: 실제 체결ID가 존재하는 주문ID(order_id) 목록 수집
    # [진입유실 근본수정] order_id만으로 판정하면, 진입 체결이 '청산'으로 오분류되어
    #  들어온 주문의 유일한 '진입' 임시행까지 삭제되어 페어링이 영구 실패한다.
    valid_order_keys = set()
    for _, row in df.iterrows():
        trade = _row_to_trade(row)
        if trade and trade.get("trade_id") and trade.get("order_id"):
            valid_order_keys.add((trade["order_id"], str(trade.get("category", "")).strip()))

    seen = set()
    seen_atomic = set()
    keep_indices = []

    for idx, row in df.iterrows():
        trade = _row_to_trade(row)
        if trade is None:
            keep_indices.append(idx)
            continue

        # [핵심] 실제 체결 이력이 존재하는 주문의 임시 기록(체결ID 없음)은 중복 방지를 위해 제거
        if not trade.get("trade_id"):
            if (trade.get("order_id"), str(trade.get("category", "")).strip()) in valid_order_keys:
                continue

        # [atomic dedupe] 합산본('a|b|c|d')/낱개('a')로 이중 기록된 동일 청산 체결 제거
        atoms = _atomic_ids(trade)
        if atoms:
            dup = atoms & seen_atomic
            if dup:
                logger.warning(
                    "[COMPACT] 중복 체결행 제거: %s %s 체결ID겹침=%s",
                    trade.get("symbol"), trade.get("category"), sorted(dup)
                )
                continue
            seen_atomic |= atoms
            keep_indices.append(idx)
            continue

        key = _trade_dedupe_key(trade)
        if key in seen:
            continue
        seen.add(key)
        keep_indices.append(idx)

    removed = len(df) - len(keep_indices)
    if removed <= 0:
        return 0

    backup_path = f"{path}.bak"
    try:
        df.to_csv(backup_path, index=False, encoding="utf-8-sig")
        df.loc[keep_indices].to_csv(path, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"[HISTORY_HELPER] CSV 저장 실패 (compact): {e}")
        return 0
        
    return removed

def aggregate_and_pair_trades(trades: List[Dict], active_positions_set: Optional[set] = None) -> List[Dict]:
    """
    1. 동일 주문ID(order_id)의 개별 체결(fill)들을 하나의 주문 단위로 합산.
    2. 동일 종목(symbol)에 대해 시간순으로 진입(Entry)과 청산(Exit)을 LONG/SHORT 방향별로 분리하여 짝지어(Pairing) 반환.
    """
    if not trades:
        return []

    trades = _dedupe_trades(trades)

    # ── 1. 주문 ID 단위로 체결 합산 ──
    for idx, t in enumerate(trades):
        if not t["order_id"] or t["order_id"] == "nan" or t["order_id"] == "":
            t["order_id"] = f"TEMP_{t['timestamp'].strftime('%Y%m%d%H%M%S')}_{idx}"

    df_fills = pd.DataFrame(trades)
    if "exit_type" not in df_fills.columns:
        df_fills["exit_type"] = ""
    if "fee" not in df_fills.columns:
        df_fills["fee"] = 0.0
    else:
        df_fills["fee"] = pd.to_numeric(df_fills["fee"], errors="coerce").fillna(0.0)
    df_fills["cost"] = df_fills["price"] * df_fills["amount"]
    df_fills["weighted_pnl_pct"] = df_fills["pnl_pct"] * df_fills["amount"]

    # [v9.9.3] 과거 이력을 '현재 모드'로 도색하지 않는다.
    # 기존엔 매매모드가 비면 CFG.USE_BLUEFROG(=지금 값)로 채워, 스위칭 이전 거래까지
    # 전부 현재 방향으로 보이게 만들어 스위칭 이력이 화면에서 사라졌다.
    # 값이 없으면 "-"로 남겨 '미기록'임을 드러낸다.
    default_mode = "-"
    if "trade_mode" not in df_fills.columns:
        df_fills["trade_mode"] = default_mode
    else:
        df_fills["trade_mode"] = df_fills["trade_mode"].replace("", default_mode).fillna(default_mode)

    # [FIX] 방향(direction)을 명시적으로 추출하여 side 차이(long vs buy)로 인한 분리 방지
    df_fills["direction"] = df_fills.apply(lambda row: get_position_direction(row["category"], row["side"]), axis=1)

    # 그룹화 항목: order_id, symbol, category, direction, leverage
    grouped = df_fills.groupby(["order_id", "symbol", "category", "direction", "leverage"], as_index=False).agg({
        "side": "first", # downstream compatibility
        "timestamp": "min",  # 가장 빠른 체결 시각
        "amount": "sum",
        "cost": "sum",
        "pnl": "sum",
        "fee": "sum",
        "trade_mode": "first",
        "weighted_pnl_pct": "sum",
        "exit_type": "max"
    })
    
    grouped["price"] = grouped["cost"] / grouped["amount"]
    grouped["pnl_pct"] = grouped["weighted_pnl_pct"] / grouped["amount"]
    grouped = grouped.drop(columns=["weighted_pnl_pct"])
    
    # 다시 딕셔너리 리스트로 변환
    orders = grouped.to_dict("records")
    orders.sort(key=lambda x: x["timestamp"])

    # ── 2. 진입/청산 페어링 (LONG / SHORT 분리 관리, M:N 매칭 지원) ──
    paired_cycles = []
    symbol_groups = {}
    
    for o in orders:
        sym = o["symbol"]
        if sym not in symbol_groups:
            symbol_groups[sym] = []
        symbol_groups[sym].append(o)

    for sym, sym_orders in symbol_groups.items():
        sym_orders.sort(key=lambda x: x["timestamp"])
        
        active_longs = []
        active_shorts = []

        for o in sym_orders:
            cat = o["category"].strip()
            direction = get_position_direction(o["category"], o["side"])
            
            if cat in ("진입", "*진입"):
                # entry 딕셔너리에 amount_remaining 필드를 초깃값 amount로 설정하여 복사본 저장
                entry_copy = dict(o)
                entry_copy["amount_remaining"] = o["amount"]
                if direction == "LONG":
                    active_longs.append(entry_copy)
                else:
                    active_shorts.append(entry_copy)
            elif cat in ("청산", "청산(로테이션)"):
                remaining_exit_amount = o["amount"]
                total_exit_pnl = o["pnl"]
                
                if direction == "LONG":
                    while remaining_exit_amount > 1e-8 and active_longs:
                        # 최근 진입 우선 매칭(LIFO): 거래소 체결 특성상 최신 진입이 최신 청산과 짝지어질 확률이 높음
                        entry = active_longs[-1]
                        match_amount = min(entry["amount_remaining"], remaining_exit_amount)
                        
                        # 분할 청산에 비례하여 PnL 분할
                        match_pnl = total_exit_pnl * (match_amount / o["amount"])
                        
                        exit_fee_share = float(o.get("fee", 0) or 0) * (match_amount / o["amount"])
                        entry_fee_share = float(entry.get("fee", 0) or 0) * (match_amount / entry["amount"]) if entry["amount"] > 0 else 0

                        paired_cycles.append({
                            "entry_time": entry["timestamp"],
                            "exit_time": o["timestamp"],
                            "symbol": sym,
                            "direction": "🟢 LONG",
                            "entry_price": entry["price"],
                            "exit_price": o["price"],
                            "amount": match_amount,
                            "pnl_usdt": match_pnl,
                            "pnl_pct": o["pnl_pct"],
                            "exit_type": o.get("exit_type", ""),
                            "fee_usdt": round(exit_fee_share + entry_fee_share, 6),
                            "trade_mode": entry.get("trade_mode", o.get("trade_mode", default_mode)),
                            "status": "청산 완료"
                        })
                        
                        entry["amount_remaining"] -= match_amount
                        remaining_exit_amount -= match_amount
                        
                        if entry["amount_remaining"] <= 1e-8:
                            active_longs.pop()
                            
                    if remaining_exit_amount > 1e-8:
                        match_pnl = total_exit_pnl * (remaining_exit_amount / o["amount"])
                        logger.warning(
                            "[진입유실 방지 자동보정] LONG %s exit=%s 미매칭수량=%.8f orderID=%s tradeID=%s",
                            sym, o["timestamp"], remaining_exit_amount,
                            o.get("order_id"), o.get("trade_id")
                        )
                        # [가짜 진입값 생성 금지] 진입 기록이 없을 때 진입가를 역산하고
                        #  진입시각을 청산 10초 전으로 만들어 정상 거래처럼 표시했다.
                        #  실측: ALLO 숏(35시간17분 보유)이 보유 10초로 표시됨.
                        #  추정값을 만들지 않고 진입유실로 정직하게 표기한다.
                        paired_cycles.append({
                            "entry_time": None,
                            "exit_time": o["timestamp"],
                            "symbol": sym,
                            "direction": "🟢 LONG",
                            "entry_price": None,
                            "exit_price": o["price"],
                            "amount": remaining_exit_amount,
                            "pnl_usdt": match_pnl,
                            "pnl_pct": o["pnl_pct"],
                            "exit_type": o.get("exit_type", ""),
                            "fee_usdt": round(float(o.get("fee", 0) or 0) * (remaining_exit_amount / o["amount"]), 6) if o["amount"] > 0 else 0,
                            "trade_mode": o.get("trade_mode", default_mode),
                            "status": "청산 완료 (진입유실)"
                        })
                else:  # SHORT
                    while remaining_exit_amount > 1e-8 and active_shorts:
                        entry = active_shorts[-1]
                        match_amount = min(entry["amount_remaining"], remaining_exit_amount)
                        
                        match_pnl = total_exit_pnl * (match_amount / o["amount"])
                        
                        exit_fee_share = float(o.get("fee", 0) or 0) * (match_amount / o["amount"])
                        entry_fee_share = float(entry.get("fee", 0) or 0) * (match_amount / entry["amount"]) if entry["amount"] > 0 else 0

                        paired_cycles.append({
                            "entry_time": entry["timestamp"],
                            "exit_time": o["timestamp"],
                            "symbol": sym,
                            "direction": "🔴 SHORT",
                            "entry_price": entry["price"],
                            "exit_price": o["price"],
                            "amount": match_amount,
                            "pnl_usdt": match_pnl,
                            "pnl_pct": o["pnl_pct"],
                            "exit_type": o.get("exit_type", ""),
                            "fee_usdt": round(exit_fee_share + entry_fee_share, 6),
                            "trade_mode": entry.get("trade_mode", o.get("trade_mode", default_mode)),
                            "status": "청산 완료"
                        })
                        
                        entry["amount_remaining"] -= match_amount
                        remaining_exit_amount -= match_amount
                        
                        if entry["amount_remaining"] <= 1e-8:
                            active_shorts.pop()
                            
                    if remaining_exit_amount > 1e-8:
                        match_pnl = total_exit_pnl * (remaining_exit_amount / o["amount"])
                        logger.warning(
                            "[진입유실 방지 자동보정] SHORT %s exit=%s 미매칭수량=%.8f orderID=%s tradeID=%s",
                            sym, o["timestamp"], remaining_exit_amount,
                            o.get("order_id"), o.get("trade_id")
                        )
                        # [가짜 진입값 생성 금지] 진입 기록이 없을 때 진입가를 역산하고
                        #  진입시각을 청산 10초 전으로 만들어 정상 거래처럼 표시했다.
                        #  실측: ALLO 숏(35시간17분 보유)이 보유 10초로 표시됨.
                        #  추정값을 만들지 않고 진입유실로 정직하게 표기한다.
                        paired_cycles.append({
                            "entry_time": None,
                            "exit_time": o["timestamp"],
                            "symbol": sym,
                            "direction": "🔴 SHORT",
                            "entry_price": None,
                            "exit_price": o["price"],
                            "amount": remaining_exit_amount,
                            "pnl_usdt": match_pnl,
                            "pnl_pct": o["pnl_pct"],
                            "exit_type": o.get("exit_type", ""),
                            "fee_usdt": round(float(o.get("fee", 0) or 0) * (remaining_exit_amount / o["amount"]), 6) if o["amount"] > 0 else 0,
                            "trade_mode": o.get("trade_mode", default_mode),
                            "status": "청산 완료 (진입유실)"
                        })
        
        # 스캔 후 남은 진입중인 포지션 표시
        for entry in active_longs:
            if entry["amount_remaining"] <= 1e-8:
                continue
            is_actually_holding = False
            if active_positions_set is not None:
                is_actually_holding = ((sym, "LONG") in active_positions_set)
            else:
                time_diff = pd.Timestamp.now() - entry["timestamp"]
                if time_diff.total_seconds() < 24 * 3600:
                    is_actually_holding = True
                
            status_str = "보유 중" if is_actually_holding else "청산 완료 (미기록)"
            
            paired_cycles.append({
                "entry_time": entry["timestamp"],
                "exit_time": None,
                "symbol": sym,
                "direction": "🟢 LONG",
                "entry_price": entry["price"],
                "exit_price": None,
                "amount": entry["amount_remaining"],
                "pnl_usdt": None,
                "pnl_pct": None,
                "exit_type": "",
                "fee_usdt": float(entry.get("fee", 0) or 0),
                "trade_mode": entry.get("trade_mode", default_mode),
                "status": status_str
            })

        for entry in active_shorts:
            if entry["amount_remaining"] <= 1e-8:
                continue
            is_actually_holding = False
            if active_positions_set is not None:
                is_actually_holding = ((sym, "SHORT") in active_positions_set)
            else:
                time_diff = pd.Timestamp.now() - entry["timestamp"]
                if time_diff.total_seconds() < 24 * 3600:
                    is_actually_holding = True
                
            status_str = "보유 중" if is_actually_holding else "청산 완료 (미기록)"
            
            paired_cycles.append({
                "entry_time": entry["timestamp"],
                "exit_time": None,
                "symbol": sym,
                "direction": "🔴 SHORT",
                "entry_price": entry["price"],
                "exit_price": None,
                "amount": entry["amount_remaining"],
                "pnl_usdt": None,
                "pnl_pct": None,
                "exit_type": "",
                "fee_usdt": float(entry.get("fee", 0) or 0),
                "trade_mode": entry.get("trade_mode", default_mode),
                "status": status_str
            })

    # 정렬 규칙: ① 보유 중(미청산)을 항상 최상단, ② 그 외는 진입시각 늦은 순(최신 위)
    def sort_key(x):
        is_holding = 1 if x.get("exit_time") is None else 0
        et = x.get("entry_time")
        et = et if et is not None else pd.Timestamp.min
        return (is_holding, et)

    paired_cycles.sort(key=sort_key, reverse=True)
    return paired_cycles


def _costs_okx(ex, begin, end):
    """OKX: 체결(fills)의 fee + 계좌청구서(bills type=8)의 펀딩비."""
    fee = pnl = funding = 0.0
    fills = 0
    after = None
    for _ in range(10):
        params = {"instType": "SWAP", "begin": begin, "limit": "100"}
        if end:
            params["end"] = end
        if after:
            params["after"] = after
        data = (ex.private_get_trade_fills_history(params) or {}).get("data", [])
        if not data:
            break
        for f in data:
            fee += float(f.get("fee") or 0)
            pnl += float(f.get("fillPnl") or 0)
            fills += 1
        after = data[-1].get("billId")
        if len(data) < 100 or not after:
            break
    try:
        params = {"instType": "SWAP", "type": "8", "begin": begin, "limit": "100"}
        if end:
            params["end"] = end
        for x in (ex.private_get_account_bills(params) or {}).get("data", []):
            funding += float(x.get("balChg") or x.get("pnl") or 0)
    except Exception as fe:
        logger.debug(f"[COSTS] OKX 펀딩비 조회 실패(무시): {fe}")
    return fee, funding, pnl, fills


def _costs_binance(ex, begin, end):
    """바이낸스 선물: income 원장에서 COMMISSION/FUNDING_FEE/REALIZED_PNL을 직접 합산."""
    fee = pnl = funding = 0.0
    fills = 0
    start = int(begin)
    for _ in range(10):
        params = {"startTime": start, "limit": 1000}
        if end:
            params["endTime"] = int(end)
        rows = ex.fapiPrivateGetIncome(params) or []
        if not rows:
            break
        for r in rows:
            t = r.get("incomeType")
            v = float(r.get("income") or 0)
            if t == "COMMISSION":
                fee += v
                fills += 1
            elif t == "FUNDING_FEE":
                funding += v
            elif t == "REALIZED_PNL":
                pnl += v
        if len(rows) < 1000:
            break
        start = int(rows[-1].get("time") or start) + 1
    return fee, funding, pnl, fills


def fetch_exchange_costs(since_dt, end_dt=None) -> Optional[Dict[str, float]]:
    """거래소 원장에서 실제 수수료·펀딩비를 직접 합산한다.

    대시보드가 '수수료+펀딩비'를 잔고 증감으로 역산(잔차)하면 거래이력 누락·입출금이
    전부 이 항목에 섞여 들어가 부호까지 뒤집힌다. 그래서 거래소 원장을 그대로 더한다.

    반환값의 부호는 거래소 원본 그대로 — 비용이면 음수, 수취면 양수.
    조회 실패 시 None을 반환하므로 호출측에서 기존 방식으로 폴백할 수 있다.
    """
    try:
        import ccxt
        try:
            from core.api_keys import load_api_keys
            load_api_keys(override=True)
        except Exception:
            pass

        exch = str(getattr(CFG, "EXCHANGE_ID", "okx")).lower()
        begin = str(int(since_dt.timestamp() * 1000))
        end = str(int(end_dt.timestamp() * 1000)) if end_dt else None

        if exch == "binance":
            key = os.getenv("BINANCE_API_KEY")
            sec = os.getenv("BINANCE_SECRET_KEY") or os.getenv("BINANCE_API_SECRET")
            if not (key and sec):
                return None
            ex = ccxt.binance({"apiKey": key, "secret": sec, "enableRateLimit": True,
                               "options": {"defaultType": "future"}})
            fee, funding, pnl, fills = _costs_binance(ex, begin, end)
        else:
            key = os.getenv("OKX_API_KEY")
            sec = os.getenv("OKX_SECRET_KEY") or os.getenv("OKX_API_SECRET")
            pw = os.getenv("OKX_PASSPHRASE") or os.getenv("OKX_API_PASSPHRASE")
            if not (key and sec and pw):
                return None
            ex = ccxt.okx({"apiKey": key, "secret": sec, "password": pw,
                           "enableRateLimit": True, "options": {"defaultType": "swap"}})
            fee, funding, pnl, fills = _costs_okx(ex, begin, end)

        return {"fee": fee, "funding": funding, "realized_pnl": pnl, "fills": fills}
    except Exception as e:
        logger.warning(f"[COSTS] 거래소 원장 수수료 조회 실패 → 폴백: {e}")
        return None


def merge_closed_by_entry(paired_rows: List[Dict]) -> List[Dict]:
    """진입건(심볼+방향+진입시각+진입가) 단위로 분할청산을 1건으로 병합한다.

    대시보드는 order_id로, 매매이력 탭은 진입건으로 각각 세고 있어 같은 기간인데도
    건수가 달랐다(8408 실측: 12건 vs 8건). 두 화면이 이 함수 하나만 쓰도록 통일한다.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    kept = []
    for row in paired_rows:
        # [유령행 제외] 진입 기록을 못 찾은 청산 중 손익이 정확히 0인 행은 실제 거래가 아니라
        # CSV 진입 누락으로 생긴 부스러기다. 같은 거래의 분할청산 한쪽이 짝을 잃은 경우가
        # 대부분이라(8405 실측: ETH 18:04:59 정상 / 18:05:01 유령, 2초 간격) 건수로 세면
        # 같은 거래를 두 번 세는 셈이 되고, 승/패 합과 총건수가 어긋나 보인다.
        if (row.get("status") == "청산 완료 (진입유실)"
                and float(row.get("pnl_usdt") or 0.0) == 0.0):
            continue
        if row.get("status") == "청산 완료" and row.get("entry_time") is not None:
            groups[(
                row.get("symbol"),
                row.get("direction"),
                row.get("entry_time"),
                float(row.get("entry_price") or 0.0),
            )].append(row)
        else:
            kept.append(row)

    merged = []
    for (sym, direction, entry_time, entry_price), rows in groups.items():
        total_amount = sum(float(r.get("amount") or 0.0) for r in rows)
        total_pnl = sum(float(r.get("pnl_usdt") or 0.0) for r in rows)
        weighted_exit = sum(float(r.get("exit_price") or 0.0) * float(r.get("amount") or 0.0) for r in rows)
        weighted_pct = sum(float(r.get("pnl_pct") or 0.0) * float(r.get("amount") or 0.0) for r in rows)
        merged.append({
            "entry_time": entry_time,
            "exit_time": max((r.get("exit_time") for r in rows if r.get("exit_time") is not None), default=None),
            "symbol": sym,
            "direction": direction,
            "entry_price": entry_price if entry_price > 0 else None,
            "exit_price": (weighted_exit / total_amount) if total_amount > 0 else None,
            "amount": total_amount,
            "pnl_usdt": total_pnl,
            "pnl_pct": (weighted_pct / total_amount) if total_amount > 0 else None,
            "fee_usdt": sum(float(r.get("fee_usdt", 0) or 0) for r in rows),
            "exit_type": (
                "T/S" if any(str(r.get("exit_type", "")).strip() == "T/S" for r in rows)
                else ("ATR" if any(str(r.get("exit_type", "")).strip() == "ATR" for r in rows) else "SL/TP")
            ),
            "trade_mode": rows[0].get("trade_mode", "역방향"),
            "status": "청산 완료",
        })
    return merged, kept


def closed_trades_since(all_trades: List[Dict], since_dt=None,
                        active_positions_set: Optional[set] = None) -> List[Dict]:
    """SINCE 이후 청산 완료된 거래를 진입건 단위로 병합해 반환한다.

    대시보드 '누적 주문 및 승률'과 매매이력 탭의 건수를 일치시키기 위한 단일 출처.
    """
    paired = aggregate_and_pair_trades(all_trades, active_positions_set=active_positions_set)
    closed = [x for x in paired if x.get("status") in ("청산 완료", "청산 완료 (진입유실)")]
    merged, kept = merge_closed_by_entry(closed)
    rows = merged + kept
    if since_dt is None:
        return rows
    out = []
    for r in rows:
        et = r.get("exit_time")
        if et is None:
            continue
        try:
            et = et.replace(tzinfo=None)
        except Exception:
            pass
        if et >= since_dt:
            out.append(r)
    return out
