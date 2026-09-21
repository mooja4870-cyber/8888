import os
import glob

target = """                                elif (grp_pnl > 0 and calculated_pnl < 0) or (grp_pnl < 0 and calculated_pnl > 0):
                                    logger.warning(
                                        f"[PNL SYNC] {sym} 부호 엇갈림 — 거래소 {grp_pnl:+.4f} 채택 "
                                        f"(로컬 계산 {calculated_pnl:+.4f} 무시)")"""

replacement = """                                elif (grp_pnl > 0 and calculated_pnl < 0) or (grp_pnl < 0 and calculated_pnl > 0):
                                    if abs(calculated_pnl) >= 0.05 or abs(grp_pnl - calculated_pnl) > 0.5:
                                        logger.warning(f"[PNL SYNC] {sym} 부호 엇갈림 — 오프라인 데이터 오염 의심! 로컬 계산({calculated_pnl:+.4f}) 강제 채택 (FoolProof)")
                                        grp_pnl = calculated_pnl
                                    else:
                                        logger.warning(
                                            f"[PNL SYNC] {sym} 부호 엇갈림 — 거래소 {grp_pnl:+.4f} 채택 "
                                            f"(로컬 계산 {calculated_pnl:+.4f} 무시)")"""

for bot_dir in glob.glob("/Users/l/project/84*"):
    engine_path = os.path.join(bot_dir, "core", "engine.py")
    if os.path.exists(engine_path):
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if target in content:
            content = content.replace(target, replacement)
            with open(engine_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Patched {engine_path}")
        else:
            print(f"Target not found in {engine_path}")
