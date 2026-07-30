import os, datetime, subprocess

today = datetime.datetime.now().strftime("%Y-%m-%d")
ver_file = "ver.md"
with open(ver_file, "r", encoding="utf-8") as f:
    c = f.read()

entry = f"""# Version History

## v2.2.34
Date: {today}

### 변경 내용
* 8개 봇 전수 '매매모드 텍스트 로깅 정합성 고도화 패치' 반영에 따른 최신 SHA-256 해시 지문(`GOLDEN_HASHES`) 100% 동기화
* 무결성 보호모드 작동 시 8개 봇 전체에 대해 위변조 오진 경고가 단 하나도 발생하지 않도록 기준 지문 최신화

### 수정 파일
* `app.py` (`GOLDEN_HASHES`)

### 비고
* ALL 8 BOTS GOLDEN_HASHES MATCH 100% 실증 검증 완료
"""
c_new = c.replace("# Version History\n", entry + "\n")
if c == c_new:
    c_new = entry + "\n" + c
with open(ver_file, "w", encoding="utf-8") as f:
    f.write(c_new)

cmd = 'git add . && git commit -m "fix: 8개 봇 매매모드 텍스트 로깅 정합성 고도화 반영 GOLDEN_HASHES 동기화 (v2.2.34)" && git tag v2.2.34 && git push origin main && git push origin v2.2.34'
res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
if res.returncode != 0:
    cmd2 = 'git push origin master && git push origin v2.2.34'
    res2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    print("8888 git push result:", res2.returncode)
else:
    print("8888 v2.2.34 commit & push SUCCESS.")
