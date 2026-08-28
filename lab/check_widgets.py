"""
설정 탭 위젯의 범위·타입을 실제 CFG 값으로 검증한다.

배경: 위젯의 min/max가 코드에 하드코딩돼 있어 config.json 값이 그 밖으로 나가면
streamlit이 StreamlitValueAboveMax/BelowMinError를 내고 **설정 탭 전체가 뜨지 않는다.**
정규식으로 훑으면 여러 줄로 쓰인 인자를 놓치므로 AST로 파싱하고, 값 표현식은
해당 봇의 실제 CFG를 넣어 평가한다.

  python3 check_widgets.py [봇번호 ...]
"""
import ast
import io
import os
import sys

BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409", "8410"]
TARGETS = {"number_input", "slider"}


def load_cfg(bot):
    """봇의 core.config.CFG를 그 봇 디렉터리 기준으로 불러온다."""
    d = f"/Users/l/project/{bot}"
    saved_path, saved_cwd = list(sys.path), os.getcwd()
    for m in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
        del sys.modules[m]
    try:
        os.chdir(d)
        sys.path.insert(0, d)
        from core.config import CFG
        return CFG
    finally:
        os.chdir(saved_cwd)
        sys.path[:] = saved_path


def widget_calls(src):
    """st.number_input / st.slider 호출을 (label, min, max, value, lineno)로 뽑는다."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in TARGETS):
            continue
        if not (isinstance(f.value, ast.Name) and f.value.id == "st"):
            continue
        args = node.args
        if len(args) < 4:          # label, min, max, value 는 위치 인자로 온다
            continue
        label = args[0].value if isinstance(args[0], ast.Constant) else "?"
        out.append((label, args[1], args[2], args[3], node.lineno))
    return out


def const(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def main():
    bots = sys.argv[1:] or BOTS
    total = 0
    for bot in bots:
        p = f"/Users/l/project/{bot}/ui/settings_tab.py"
        if not os.path.exists(p):
            continue
        try:
            cfg = load_cfg(bot)
        except Exception as e:
            print(f"[{bot}] CFG 로드 실패: {e}")
            continue
        src = io.open(p, encoding="utf-8").read()
        bad = []
        for label, lo_n, hi_n, val_n, line in widget_calls(src):
            lo, hi = const(lo_n), const(hi_n)
            if lo is None or hi is None:
                continue
            expr = ast.unparse(val_n) if hasattr(ast, "unparse") else None
            if expr is None:
                continue
            try:
                val = eval(expr, {"CFG": cfg, "getattr": getattr,
                                  "float": float, "int": int, "round": round,
                                  "min": min, "max": max, "abs": abs})
            except Exception:
                continue
            try:
                fv = float(val)
            except Exception:
                continue
            why = []
            if fv < float(lo):
                why.append(f"최소 미만 {val} < {lo}")
            if fv > float(hi):
                why.append(f"최대 초과 {val} > {hi}")
            if isinstance(lo, int) and isinstance(hi, int) and isinstance(val, float):
                why.append(f"타입 불일치 int범위에 float {val}")
            if why:
                bad.append((line, label, expr, "; ".join(why)))
        if bad:
            total += len(bad)
            print(f"\n[{bot}] {len(bad)}건")
            for line, label, expr, why in bad:
                print(f"   L{line:<5d} {label[:24]:26s} {why}")
                print(f"          {expr}")
        else:
            print(f"[{bot}] 이상 없음")
    print(f"\n총 {total}건")


if __name__ == "__main__":
    main()
