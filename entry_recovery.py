import os
import csv
import time
from datetime import datetime, timedelta

# 대상 봇 목록
VENUE = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def log(msg):
    print(msg)

def recover_entries(bot, dry=False):
    path = os.path.join(BASE, bot, "data", "trade_history.csv")
    if not os.path.exists(path):
        return 0
    
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return 0
        rows = list(reader)
        
    # 상태 추적
    positions = {} # symbol: current qty
    new_rows = []
    recovered_count = 0
    
    for row in rows:
        if len(row) < 14:
            new_rows.append(row)
            continue
            
        ts_str = row[0]
        sym = row[1]
        kind = row[2]
        direction = row[3] # 진입: long/short, 청산: sell/buy
        
        try:
            price = float(row[4])
            qty = float(row[5])
            pnl_usdt = float(row[6])
            leverage = int(row[9])
        except ValueError:
            new_rows.append(row)
            continue
            
        if kind == "진입":
            positions[sym] = positions.get(sym, 0.0) + qty
            new_rows.append(row)
        elif kind == "청산":
            current_qty = positions.get(sym, 0.0)
            if current_qty >= qty * 0.99: # 오차 허용
                positions[sym] -= qty
                new_rows.append(row)
            else:
                # 진입 유실 발생 (현재 보유 수량보다 청산 수량이 큼)
                shortfall = qty - current_qty
                
                # 진입 단가 역산 (PnL USDT 기반)
                # 방향: 청산이 sell이면 진입은 long, 청산이 buy면 진입은 short
                if direction.lower() == "sell": # Long exit
                    entry_side = "long"
                    # pnl = (exit - entry) * shortfall
                    # entry = exit - pnl / shortfall
                    entry_price = price - (pnl_usdt / shortfall)
                elif direction.lower() == "buy": # Short exit
                    entry_side = "short"
                    # pnl = (entry - exit) * shortfall
                    # entry = exit + pnl / shortfall
                    entry_price = price + (pnl_usdt / shortfall)
                else:
                    new_rows.append(row)
                    continue
                
                entry_price = max(0.0, entry_price) # 안전 장치
                
                # 1분 전 시간으로 가짜 진입 타임스탬프 생성
                try:
                    exit_dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    entry_dt = exit_dt - timedelta(minutes=1)
                except Exception:
                    entry_dt = datetime.now()
                
                entry_ts_str = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
                
                # 진입 row 생성
                # 헤더: 시간,심볼,유형,방향,가격,수량,수익(USDT),수익률(%),청산유형,레버리지,주문ID,체결ID,수수료(USDT),매매모드
                # [0] 시간 [1] 심볼 [2] 유형 [3] 방향 [4] 가격 [5] 수량 [6] 수익 [7] 수익률 [8] 청산유형 [9] 레버리지
                # [10] 주문ID [11] 체결ID [12] 수수료 [13] 매매모드
                recovery_row = [
                    entry_ts_str, sym, "진입", entry_side, f"{entry_price:.8f}", str(shortfall),
                    "0.0", "0.0", "SL/TP", str(leverage), "RECOVERED_ENTRY", "", "0.0", row[13]
                ]
                
                new_rows.append(recovery_row)
                new_rows.append(row)
                
                # 0으로 맞춤 (shortfall 만큼 진입했다고 쳤으므로)
                positions[sym] = 0.0
                recovered_count += 1
                
                log(f"  [{bot}] 진입유실 복구: {sym} {entry_side} 단가 {entry_price:.4f} 수량 {shortfall}")
    
    if recovered_count > 0 and not dry:
        # 날짜순 정렬 후 저장
        # 정렬 키: 날짜(문자열)
        def get_ts(r):
            return r[0]
        new_rows.sort(key=get_ts)
        
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(new_rows)
        os.replace(tmp, path)
        
    return recovered_count

def main():
    import sys
    dry = "--dry" in sys.argv
    total = 0
    for bot in VENUE:
        try:
            cnt = recover_entries(bot, dry)
            total += cnt
        except Exception as e:
            log(f"[{bot}] 오류: {e}")
            
    if total > 0:
        verb = "발견(기록 안 함)" if dry else "자동 복구 완료"
        log(f"🛠️ 총 {total}건의 진입유실(Orphaned Exit) {verb}")
    else:
        log("✅ 이상 없음 — 진입유실 기록 없음")

if __name__ == "__main__":
    main()
