#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매 5분 정각(00:00, 05:00, 10:00, 15:00... 55:00) 8개 봇 개별 40분 파동 차트 알림 전용 독립 상시 데몬
"""
import os
import sys
import time
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import app
import discord_alert


def send_once():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 매 5분 정각 8개 봇 개별 파동 알림 즉시 발송 시도...", flush=True)
    try:
        data = app.collect()
        ok, info = discord_alert.tick(data, tick_count=0, include_bot_charts=True)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 발송 결과: ok={ok} info={info}", flush=True)
        return ok
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 발송 예외: {e}", flush=True)
        return False


def main():
    print(f"🚀 [{time.strftime('%Y-%m-%d %H:%M:%S')}] 매 5분 정각 8개 봇 개별 40분 파동 차트 스케줄러 가동 중...", flush=True)
    loop_count = 0
    while True:
        now = time.time()
        dt = datetime.fromtimestamp(now)
        # 매 5분 정각 계산 (00, 05, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55분 00초)
        min_mod = dt.minute % 5
        sec_diff = min_mod * 60 + dt.second + dt.microsecond / 1e6
        if sec_diff < 0.5:
            target_time = now
        else:
            target_time = now + (300 - sec_diff)
            
        sleep_sec = target_time - time.time()
        if sleep_sec > 0.5:
            target_str = datetime.fromtimestamp(target_time).strftime("%H:%M:%S")
            print(f"⏱️ 다음 5분 정각 알림 대기: {sleep_sec:.1f}초 (목표: {target_str})", flush=True)
            time.sleep(sleep_sec)

        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] 매 5분 정각 8개 봇 개별 파동 알림 발송 시도...", flush=True)
        try:
            data = app.collect()
            ok, info = discord_alert.tick(data, tick_count=loop_count, include_bot_charts=True)
            loop_count += 1
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 5분 정각 알림 발송 완료: ok={ok} info={info}", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 5분 정각 알림 발송 예외: {e}", flush=True)
            
        # 중복 발송 방지를 위해 15초 대기
        time.sleep(15)


if __name__ == "__main__":
    if "--once" in sys.argv:
        send_once()
    else:
        main()
