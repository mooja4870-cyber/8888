import sys
import os
import app
import discord_alert

def fake_post(content):
    print("--- DISCORD MESSAGE ---")
    print(content)
    print("-----------------------")
    return True, "status=204"

discord_alert._post = fake_post
ok, info = discord_alert.tick(app.collect())
print(f"[DISCORD] 발송 {'성공' if ok else '실패'}: {info}")
