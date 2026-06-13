"""
로컬 PC 전용 — 8888 대시보드의 /api/status 스냅샷을 GitHub Gist에 주기 업로드.
Streamlit Cloud 앱(streamlit_app.py)이 그 Gist를 읽어 표시한다.
실거래 키는 올리지 않음(요약 JSON만). 의존성 0(표준 라이브러리).

사용:
  export GITHUB_TOKEN=ghp_xxx          # gist 수정 권한(scope: gist) 토큰
  export GIST_ID=<gist id>             # 미리 만든 gist의 id (snapshot.json 파일 포함)
  python3 publish_snapshot.py [업로드주기초=30]

토큰/ID는 환경변수로만 받는다(소스·repo에 비밀 미기록).
"""
import json
import os
import sys
import time
import urllib.request

LOCAL_API = "http://localhost:8888/api/status"
GIST_FILE = "snapshot.json"


def fetch_local():
    with urllib.request.urlopen(LOCAL_API, timeout=8) as r:
        return r.read().decode("utf-8")


def push_gist(token, gist_id, content):
    body = json.dumps({"files": {GIST_FILE: {"content": content}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}", data=body, method="PATCH",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def main():
    token = os.getenv("GITHUB_TOKEN", "")
    gist_id = os.getenv("GIST_ID", "")
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    if not token or not gist_id:
        print("[ERR] GITHUB_TOKEN / GIST_ID 환경변수 필요"); return
    print(f"[publish] 시작 — 매 {interval}s, gist {gist_id[:6]}…")
    while True:
        try:
            snap = fetch_local()
            st = push_gist(token, gist_id, snap)
            print(f"[publish] {time.strftime('%H:%M:%S')} 업로드 OK (HTTP {st}, {len(snap)}B)")
        except Exception as e:
            print(f"[publish] 오류: {str(e)[:120]}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
