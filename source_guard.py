#!/usr/bin/env python3
"""source_guard.py — 8403 소스 완전무장 (2026-08-25, mooja 지시)

무엇을 막나
──────────
mooja와 내가 함께 의논해 푸는 경우가 아니면 **8403의 소스가 어떤 경로로도 바뀌지 않게** 한다.
외부 IDE(Antigravity 등), 자동 도구, 실수로 인한 편집 모두 대상이다.

두 겹으로 막는다
  ① 예방 — 파일에 macOS 잠금 플래그(`chflags uchg`)를 건다. 잠긴 파일은 편집기가
     저장을 시도하면 곧바로 실패한다. 사고가 '조용히' 일어나지 않고 그 자리에서 드러난다.
  ② 복원 — 그래도 바뀌면(플래그를 푼 뒤 고친 경우 등) 금고(_vault)의 원본으로
     되돌리고 디스코드로 알린다. 워치독이 5분 주기로 부른다.

왜 git이 아니라 금고인가
  git은 HEAD가 움직이면 기준이 흔들린다. 실제로 외부 도구가 커밋을 만든 이력이 있다.
  그래서 **저장소와 무관한 사본**을 따로 두고 그것을 유일한 기준으로 삼는다.

무엇을 지키나 / 안 지키나
  · 지킨다: 8403의 .py 전부 (최상위 + core/ + ui/)
  · 안 지킨다: config.json(설정은 config_sentinel 담당), data/, 로그, venv, __pycache__, *.bak*
    → 봇이 돌면서 써야 하는 파일을 잠그면 봇이 죽는다.

사용법
  python3 source_guard.py --seal      현재 소스를 기준으로 봉인(금고 저장 + 잠금)
  python3 source_guard.py --check     대조만 (복원·알림 없음)
  python3 source_guard.py --unlock    잠금 해제 (비번 불필요)
  python3 source_guard.py --lock      다시 잠금 (금고는 그대로)
  python3 source_guard.py --reseal    고친 내용을 새 기준으로 다시 봉인
  python3 source_guard.py             대조 → 어긋나면 복원 + 알림 (워치독용)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

BASE = "/Users/l/project"
HERE = os.path.join(BASE, "8888")
TARGET = "8403"
SRC_ROOT = os.path.join(BASE, TARGET)
VAULT = os.path.join(HERE, "_vault", TARGET)
MANIFEST = os.path.join(HERE, "_vault", f"manifest_{TARGET}.json")
LOG = os.path.join(HERE, "source_guard.log")

SCAN_DIRS = ["", "core", "ui"]          # 최상위 + core + ui
SKIP_PARTS = ("venv", "__pycache__", ".git", "_backup", "data")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(msg):
    """디스코드 알림 — config_sentinel과 같은 발송 경로를 쓴다."""
    try:
        sys.path.insert(0, HERE)
        from profit_guard import post_discord
        post_discord(msg)
    except Exception as e:
        log(f"  (디스코드 알림 실패: {str(e)[:80]})")


def targets():
    """지켜야 할 .py 상대경로 목록."""
    out = []
    for d in SCAN_DIRS:
        p = os.path.join(SRC_ROOT, d) if d else SRC_ROOT
        if not os.path.isdir(p):
            continue
        for name in sorted(os.listdir(p)):
            if not name.endswith(".py") or ".bak" in name:
                continue
            rel = os.path.join(d, name) if d else name
            if any(s in rel for s in SKIP_PARTS):
                continue
            if os.path.isfile(os.path.join(SRC_ROOT, rel)):
                out.append(rel)
    return out


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def chflags(flag, paths):
    """macOS 잠금 플래그. 실패해도 복원 기능은 계속 동작해야 하므로 예외를 삼킨다."""
    ok = 0
    for p in paths:
        try:
            subprocess.run(["chflags", flag, p], check=True,
                           capture_output=True, timeout=10)
            ok += 1
        except Exception:
            pass
    return ok


def live_paths(rels):
    return [os.path.join(SRC_ROOT, r) for r in rels]


def seal():
    rels = targets()
    chflags("nouchg", live_paths(rels))          # 재봉인 대비 선해제
    if os.path.isdir(VAULT):
        shutil.rmtree(VAULT)
    man = {}
    for rel in rels:
        src = os.path.join(SRC_ROOT, rel)
        dst = os.path.join(VAULT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        man[rel] = {"sha256": sha(src), "size": os.path.getsize(src)}
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"sealed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "target": TARGET, "files": man}, f, ensure_ascii=False, indent=2)
    n = chflags("uchg", live_paths(rels))
    log(f"봉인 완료 — {len(rels)}개 파일 금고 저장 · {n}개 잠금")
    return 0


def load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def diff():
    """(변경, 삭제, 신규) 상대경로 목록."""
    man = load_manifest()
    if not man:
        return None
    files = man["files"]
    changed, missing = [], []
    for rel, meta in files.items():
        p = os.path.join(SRC_ROOT, rel)
        if not os.path.exists(p):
            missing.append(rel)
        elif sha(p) != meta["sha256"]:
            changed.append(rel)
    added = [r for r in targets() if r not in files]
    return changed, missing, added


def restore(rels):
    """금고 원본으로 되돌린다. 잠금을 잠깐 풀고 다시 건다."""
    paths = live_paths(rels)
    chflags("nouchg", paths)
    done = []
    for rel in rels:
        src = os.path.join(VAULT, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(SRC_ROOT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        done.append(rel)
    chflags("uchg", paths)
    return done


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg in ("--seal", "--reseal"):
        return seal()

    if arg == "--unlock":
        # [2026-08-26] mooja 지시로 **비번 관문 제거**. 이제 바로 열린다.
        # 잠금과 금고 자동복원은 그대로 남는다 — 실수·외부도구의 조용한 수정은 계속 막는다.
        n = chflags("nouchg", live_paths(targets()))
        log(f"🔓 잠금 해제 — {n}개. 수정 뒤 반드시 --reseal 또는 --lock 할 것")
        notify(f"🔓 **8403 소스 잠금 해제됨** ({n}개)\n"
               f"시각: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
               f"수정을 마치면 `--reseal` 로 다시 봉인할 것")
        return 0

    if arg == "--lock":
        n = chflags("uchg", live_paths(targets()))
        log(f"🔒 잠금 — {n}개")
        return 0

    d = diff()
    if d is None:
        log("금고 없음 — 먼저 --seal 로 봉인할 것")
        return 1
    changed, missing, added = d

    if arg == "--check":
        if not (changed or missing):
            log(f"이상 없음 — {TARGET} 소스 {len(load_manifest()['files'])}개 원본과 일치"
                + (f" (금고 밖 신규 {len(added)}개)" if added else ""))
        else:
            log(f"⚠️ 변경 {len(changed)} · 삭제 {len(missing)}: "
                + ", ".join((changed + missing)[:8]))
        return 0

    # 기본 모드 — 워치독이 5분마다 부른다
    if not (changed or missing):
        log(f"이상 없음 — {TARGET} 소스 잠금 유지")
        return 0

    hit = changed + missing
    done = restore(hit)
    log(f"🛡 {TARGET} 소스 변조 감지 → 원본 복원 {len(done)}개: " + ", ".join(hit[:8]))
    notify(f"🛡 **8403 소스 변조 감지 → 자동 복원**\n"
           f"변경 {len(changed)}건 · 삭제 {len(missing)}건\n"
           f"```{chr(10).join(hit[:10])}```\n"
           f"봉인 기준: {load_manifest().get('sealed_at')}\n"
           f"의도한 수정이라면 `python3 8888/source_guard.py --unlock` 후 고치고 `--reseal`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
