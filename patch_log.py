import os

TARGET_BOTS = ['8401', '8402', '8403', '8404', '8405', '8408', '8410']

OLD_CODE = '''    def get_scanner_logs(self, last_n: int = 50) -> list[str]:
        if not self.scanner:
            return ["[SYS] 엔진 미연결"]
        try:
            future = asyncio.run_coroutine_threadsafe(self.scanner.get_logs(last_n), self._loop)
            return future.result(timeout=1.0)  # [perf] 렌더 무한 블로킹 방지
        except Exception:
            return ["[SYS] 로그 조회 지연/타임아웃"]'''

NEW_CODE = '''    def get_scanner_logs(self, last_n: int = 50) -> list[str]:
        """UI(대시보드)에서 호출: 엔진 로그 파일을 직접 읽어옵니다."""
        import os
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_engine.log")
        try:
            if not os.path.exists(log_path):
                return ["[SYS] 로그 파일이 아직 생성되지 않았습니다"]
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-last_n:] if line.strip()]
        except Exception as e:
            return [f"[SYS] 로그 읽기 에러: {e}"]'''

def patch_bot(bot_id):
    filepath = f"/Users/l/project/{bot_id}/core/engine.py"
    if not os.path.exists(filepath):
        print(f"[{bot_id}] File not found: {filepath}")
        return
        
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    if OLD_CODE in content:
        content = content.replace(OLD_CODE, NEW_CODE)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[{bot_id}] Successfully patched {filepath}")
    elif "bot_engine.log" in content:
        print(f"[{bot_id}] Already patched.")
    else:
        print(f"[{bot_id}] Target code not found. Could not patch.")

if __name__ == "__main__":
    for bot in TARGET_BOTS:
        patch_bot(bot)
