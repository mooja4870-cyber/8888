#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8888 양방향 디스코드 원격 제어 봇 (Discord Interactive Control Engine)
- 외부 디스코드에서 명령어(!상태, !모드 8403 역, !초기화 8409, !재가동 8405)를 입력받아
  Antigravity IDE 지시와 동일하게 봇 설정을 즉시 변경하고 결과를 디스코드로 답신.
"""

import os
import sys
import json
import time
import asyncio
import urllib.request
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import app
import discord_alert

TOKEN_PATH = os.path.join(BASE_DIR, "discord_bot_token.txt")
WEBHOOK_PATH = os.path.join(BASE_DIR, "discord_webhook.txt")

def load_bot_token():
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return os.environ.get("DISCORD_BOT_TOKEN", "").strip()

def send_discord_reply(content):
    """디스코드 답신 (Webhook 또는 API 이용)"""
    return discord_alert._post(content)

def handle_command(cmd_text):
    """명령어 파싱 및 실행 핸들러"""
    cmd_text = cmd_text.strip()
    if not cmd_text.startswith("!"):
        return None

    parts = cmd_text.split()
    cmd = parts[0].lower()

    # 1) !상태 (전체 봇 상태 리포트)
    if cmd in ("!상태", "!status", "!info"):
        d = app.collect()
        msg = discord_alert.build_message(d, None, {}, [], " [원격 상태 리포트]")
        return f"📱 **[원격 제어 상태 리포트]**\n{msg}"

    # 2) !모드 <봇번호> <순|역> (예: !모드 8403 역, !mode 8403 reverse)
    elif cmd in ("!모드", "!mode"):
        if len(parts) < 3:
            return "❌ **사용법**: `!모드 <봇번호> <순|역>` (예: `!모드 8403 역` 또는 `!모드 8402 순`)"
        bot_id = parts[1].strip()
        mode_val = parts[2].strip().lower()

        valid_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
        if bot_id not in valid_bots:
            return f"❌ **오류**: 존재하지 않는 봇 번호입니다. ({', '.join(valid_bots)})"

        if mode_val in ("역", "역방향", "reverse", "bluefrog", "true", "1"):
            use_bf = True
            mode_label = "역 (역방향 / 청개구리)"
        elif mode_val in ("순", "순방향", "forward", "false", "0"):
            use_bf = False
            mode_label = "순 (순방향)"
        else:
            return "❌ **오류**: 매매모드는 `순` 또는 `역`이어야 합니다."

        # config.json 수정
        cfg_path = f"/Users/l/project/{bot_id}/config.json"
        if not os.path.exists(cfg_path):
            return f"❌ **오류**: {bot_id} 봇의 config.json 파일을 찾을 수 없습니다."

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["USE_BLUEFROG"] = use_bf
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            return f"❌ **설정 수정 실패**: {e}"

        # 8888 집계 재수집 테스트
        d = app.collect()
        return f"✅ **[{bot_id} 봇 매매모드 원격 변경 완료]**\n• 변경 모드: **{mode_label}**\n• {bot_id} config.json 설정 반영 및 8888 관제 대시보드 동기화 완료!"

    # 3) !초기화 <봇번호> (예: !초기화 8409)
    elif cmd in ("!초기화", "!reset"):
        if len(parts) < 2:
            return "❌ **사용법**: `!초기화 <봇번호>` (예: `!초기화 8409`)"
        bot_id = parts[1].strip()
        valid_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
        if bot_id not in valid_bots:
            return f"❌ **오류**: 존재하지 않는 봇 번호입니다."

        stats_p = f"/Users/l/project/{bot_id}/data/stats.json"
        now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # 실시간 잔고 수집
        d = app.collect()
        bot_info = [b for b in d["bots"] if b["name"] == bot_id]
        new_seed = 10.0
        if bot_info and bot_info[0].get("ex_balance"):
            new_seed = float(bot_info[0]["ex_balance"])

        try:
            st_data = {}
            if os.path.exists(stats_p):
                with open(stats_p, encoding="utf-8") as f:
                    st_data = json.load(f)
            st_data["seed_money"] = round(new_seed, 4)
            st_data["perf_start_time"] = now_str
            st_data["total_wins"] = 0
            st_data["total_losses"] = 0
            st_data["total_pnl_usdt"] = 0.0

            with open(stats_p, "w", encoding="utf-8") as f:
                json.dump(st_data, f, ensure_ascii=False, indent=2)

            # seeds.json 동기화
            app.sync_seed_info(bot_id, new_seed, now_str)
        except Exception as e:
            return f"❌ **초기화 실패**: {e}"

        return f"✅ **[{bot_id} 봇 초기화 완료]**\n• 기준 시드: **{new_seed:.4f} USDT**\n• 초기화 시각: **{now_str}**\n• 8888 앱 집계 및 디스코드 리포트 갱신 완료!"

    # 4) !재가동 <봇번호> (예: !재가동 8405)
    elif cmd in ("!재가동", "!restart"):
        if len(parts) < 2:
            return "❌ **사용법**: `!재가동 <봇번호>` (예: `!재가동 8405`)"
        bot_id = parts[1].strip()
        valid_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
        if bot_id not in valid_bots:
            return f"❌ **오류**: 존재하지 않는 봇 번호입니다."

        run_script = f"/Users/l/project/{bot_id}/run.sh"
        if not os.path.exists(run_script):
            return f"❌ **오류**: {bot_id} 봇의 run.sh 가 존재하지 않습니다."

        try:
            import subprocess
            res = subprocess.run(["bash", run_script], capture_output=True, text=True, timeout=15)
            return f"✅ **[{bot_id} 봇 재가동 조치 완료]**\n```text\n{res.stdout[-400:]}\n```"
        except Exception as e:
            return f"❌ **재가동 실패**: {e}"

    elif cmd in ("!도움말", "!help"):
        return ("ℹ️ **[8888 디스코드 원격 제어 봇 도움말]**\n"
                "• `!상태` : 8개 봇 전체 실시간 수치 및 매매모드 리포트\n"
                "• `!모드 <봇번호> <순|역>` : 해당 봇의 매매모드 즉시 변경 (예: `!모드 8403 역`)\n"
                "• `!초기화 <봇번호>` : 해당 봇 시드 및 초기화 시각 리셋 (예: `!초기화 8409`)\n"
                "• `!재가동 <봇번호>` : 해당 봇 프로세스 안전 재가동 (예: `!재가동 8405`)")

    return None

async def run_gateway_listener():
    """Discord Gateway API v10 Websocket Listener"""
    import websockets
    token = load_bot_token()
    if not token:
        print("[DISCORD BOT] Token not found in discord_bot_token.txt or env. Listener waiting for token.")
        return

    gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"
    print(f"[DISCORD BOT] Connecting to Gateway API...")

    while True:
        try:
            async with websockets.connect(gateway_url) as ws:
                # Receive Hello
                hello = await ws.recv()
                hello_data = json.loads(hello)
                heartbeat_interval = hello_data["d"]["heartbeat_interval"] / 1000.0

                # Identify
                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": token,
                        "intents": 513, # GUILDS + GUILD_MESSAGES
                        "properties": {
                            "os": "macOS",
                            "browser": "8888-bot",
                            "device": "8888-bot"
                        }
                    }
                }
                await ws.send(json.dumps(identify_payload))

                async def heartbeat():
                    while True:
                        await asyncio.sleep(heartbeat_interval)
                        await ws.send(json.dumps({"op": 1, "d": None}))

                hb_task = asyncio.create_task(heartbeat())

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    op = data.get("op")
                    t = data.get("t")

                    if t == "MESSAGE_CREATE":
                        d = data.get("d", {})
                        content = d.get("content", "")
                        author = d.get("author", {})
                        # Bot 본인 메시지 무시
                        if author.get("bot"):
                            continue

                        reply = handle_command(content)
                        if reply:
                            send_discord_reply(reply)

        except Exception as e:
            print(f"[DISCORD BOT] Connection lost: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("=== DISCORD BOT HANDLER TEST ===")
        print(handle_command("!도움말"))
        print("---")
        print(handle_command("!상태"))
        print("---")
        print(handle_command("!모드 8403 역"))
    else:
        asyncio.run(run_gateway_listener())
