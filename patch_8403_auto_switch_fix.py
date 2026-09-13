#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8403 봇 매매방향 자동 스위칭(Auto Mode Switch) 긴급 정상화 패치
- 4전 3패(xxOx, xOxx, xxxO, xxxx) 누락 버그 해결
- 과거 stale switch_state.json 키로 인한 윈도우 증발(M=0/1) 버그 해결
- config.json 원자적 반영 및 중복 스위칭 방지
"""
import os
import sys
import json
import shutil

ENGINE_PATH = "/Users/l/project/8403/core/engine.py"
BACKUP_PATH = "/Users/l/project/8403/core/engine.py.bak_switch_fix_20260913"

OLD_TARGET = '''            # 동일 마지막 체결에 대해 이미 스위칭을 수행했으면 중복 스위칭 방지
            if last_switched_key == latest_key:
                return

            # [2026-09-03 기준 정리] 스위칭 후에는 **승패 기록을 리셋**하고
            # 그 이후 거래만으로 재전환을 판단한다.
            #
            # 종전 방식의 문제: 쿨다운 3건이 지나면 '전체 이력의 최근 5전'을 봤는데,
            # 그 5전에 스위칭 이전 거래가 2건 섞여 들어갔다. 방향을 이미 바꿨는데
            # 바꾸기 전의 패배가 다시 재전환 근거가 되니 기준이 애매했다.
            #
            # 새 기준 (예: 순방향 시작 → 승승패패패 → 역방향 전환)
            #   · 이후 '패' 1건    → 새 기록 1건, 판단 보류 (역방향 유지)
            #   · 이후 '패' 2건    → 새 기록 2건, 판단 보류 (역방향 유지)
            #   · 이후 '패' 3건    → 새 기록 3건이 전부 패 → 재전환
            # 새 기록이 3건 미만이면 판단하지 않으므로, 쿨다운 장치가 따로 필요 없다.
            _base = last_switched_on_count if last_switched_on_count and last_switched_on_count > 0 else 0
            if _base > N:
                _base = 0          # 이력이 줄어든 흔적(초기화 등) — 기준점을 되돌린다
            window = closed_trades[_base:]
            M = len(window)
            if M < 3:
                return

            should_switch = False
            reason_msg = ""
            pattern_str = ""

            def _lost(_t):
                return float(_t.get("pnl_usdt") or 0.0) < 0.0

            if M >= 5:
                # [5전 3패] 스위칭 이후 기록의 최근 5전 중 3패 이상이면 전환
                recent_5 = window[-5:]
                losses = sum(1 for t in recent_5 if _lost(t))
                if losses >= 3:
                    should_switch = True
                    seq = "".join(["x" if _lost(t) else "O" for t in recent_5])
                    pattern_str = seq
                    reason_msg = f"스위칭 후 5전 중 {losses}패({seq})"
            elif all(_lost(t) for t in window[-3:]):
                # 새 기록이 3~4건뿐일 때는 '전부 패'만 전환 근거로 인정
                should_switch = True
                pattern_str = "xxx"
                reason_msg = f"스위칭 후 3연패(xxx) 발생 (새 기록 {M}건)"

            if should_switch:
                try:
                    with open(state_file, "w", encoding="utf-8") as sf:
                        json.dump({
                            "last_switched_key": latest_key,
                            "last_switched_on_count": N,
                            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "reason": reason_msg,
                            "pattern": pattern_str
                        }, sf, indent=2)
                except Exception:
                    pass

                self._last_switched_trade_keys = (latest_key,)
                cur_mode = getattr(self.cfg, "USE_BLUEFROG", True)
                new_mode = not cur_mode
                self.cfg.USE_BLUEFROG = new_mode
                self.cfg.save_settings()

                old_mode_str = "🐸 청개구리 모드(역매매) [역]" if cur_mode else "🎯 정방향 매매 모드 [순]"
                new_mode_str = "🐸 청개구리 모드(역매매) [역]" if new_mode else "🎯 정방향 매매 모드 [순]"

                logger.warning(f"[AUTO MODE SWITCH] {reason_msg}! 매매방향 대칭 자동 스위칭: {old_mode_str} ➡️ {new_mode_str}")

                try:
                    from core.alert import send_telegram_alert
                    alert_msg = (
                        f"⚡ **매매방향 자동 스위칭 발동!**\\n"
                        f"----------------------------------------\\n"
                        f"📊 **발동 사유**: {reason_msg}\\n"
                        f"🔄 **모드 전환**: {old_mode_str} ➡️ **{new_mode_str}**\\n"
                        f"⏱ **전환 시각**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
                        f"----------------------------------------\\n"
                        f"💡 대칭 반전 매매가 즉시 적용됩니다."
                    )
                    send_telegram_alert(alert_msg)
                except Exception as ae:
                    logger.error(f"[AUTO MODE SWITCH] 알림 발송 실패: {ae}")
        except Exception as e:
            logger.error(f"[AUTO MODE SWITCH] 오류 발생: {e}")'''

NEW_REPLACEMENT = '''            # 동일 마지막 체결에 대해 이미 스위칭을 수행했으면 중복 스위칭 방지
            if last_switched_key and str(last_switched_key) == latest_key:
                return

            # 스위칭 기준선(Window) 산정:
            # 1. last_switched_key가 현재 closed_trades 내에 존재하는지 확인
            # 2. 존재하면 그 체결 이후의 거래들만 window로 설정
            # 3. 존재하지 않는 과거 키이거나 없으면 현재 closed_trades 전체가 window
            matched_idx = -1
            if last_switched_key:
                for idx, t in enumerate(closed_trades):
                    t_key = str(t.get("exit_time") or t.get("timestamp"))
                    if t_key == str(last_switched_key):
                        matched_idx = idx
                        break

            if matched_idx >= 0:
                window = closed_trades[matched_idx + 1:]
            else:
                # 과거 stale 키이거나 이력이 정리된 경우:
                # switch_state의 updated_at 시각이 있다면 그 시각 이후 거래들만 필터링하거나 전체 이력 사용
                _anchor = str(sdata.get("updated_at") or "")
                if _anchor:
                    after_anchor = [t for t in closed_trades if str(t.get("exit_time") or "") > _anchor]
                    if len(after_anchor) >= 3:
                        window = after_anchor
                    else:
                        window = list(closed_trades)
                else:
                    window = list(closed_trades)

            M = len(window)
            if M < 3:
                return

            should_switch = False
            reason_msg = ""
            pattern_str = ""

            def _lost(_t):
                return float(_t.get("pnl_usdt") or 0.0) < 0.0

            if M >= 5:
                # [5전 3패] 스위칭 이후 기록의 최근 5전 중 3패 이상이면 전환
                recent_5 = window[-5:]
                losses = sum(1 for t in recent_5 if _lost(t))
                if losses >= 3:
                    should_switch = True
                    seq = "".join(["x" if _lost(t) else "O" for t in recent_5])
                    pattern_str = seq
                    reason_msg = f"스위칭 후 5전 중 {losses}패({seq})"
            elif M == 4:
                # [4전 3패 이상] (xxxO, xxOx, xOxx, xxxx) 즉시 전환
                losses = sum(1 for t in window if _lost(t))
                if losses >= 3:
                    should_switch = True
                    seq = "".join(["x" if _lost(t) else "O" for t in window])
                    pattern_str = seq
                    reason_msg = f"초기 4전 중 {losses}패({seq}) 발생"
            elif M == 3 and all(_lost(t) for t in window):
                # [3전 3연패] (xxx) 즉시 전환
                should_switch = True
                pattern_str = "xxx"
                reason_msg = f"초기 3연패(xxx) 발생"

            if should_switch:
                try:
                    with open(state_file, "w", encoding="utf-8") as sf:
                        json.dump({
                            "last_switched_key": latest_key,
                            "last_switched_on_count": N,
                            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "reason": reason_msg,
                            "pattern": pattern_str
                        }, sf, indent=2, ensure_ascii=False)
                except Exception:
                    pass

                self._last_switched_trade_keys = (latest_key,)
                
                # config.json 실시간 직접 확인 및 업데이트
                cur_mode = getattr(self.cfg, "USE_BLUEFROG", False)
                try:
                    import json as _json
                    from core.config import CONFIG_FILE as _CF
                    with open(_CF, "r", encoding="utf-8") as _f:
                        cur_mode = bool(_json.load(_f).get("USE_BLUEFROG", cur_mode))
                except Exception:
                    pass
                new_mode = not cur_mode
                self.cfg.USE_BLUEFROG = new_mode
                
                try:
                    import json as _json
                    from core.config import CONFIG_FILE as _CF
                    with open(_CF, "r", encoding="utf-8") as _f:
                        _d = _json.load(_f)
                    _d["USE_BLUEFROG"] = new_mode
                    with open(_CF, "w", encoding="utf-8") as _f:
                        _json.dump(_d, _f, indent=2, ensure_ascii=False)
                except Exception:
                    self.cfg.save_settings()

                old_mode_str = "🐸 청개구리 모드(역매매) [역]" if cur_mode else "🎯 정방향 매매 모드 [순]"
                new_mode_str = "🐸 청개구리 모드(역매매) [역]" if new_mode else "🎯 정방향 매매 모드 [순]"

                logger.warning(f"[AUTO MODE SWITCH] {reason_msg}! 매매방향 대칭 자동 스위칭: {old_mode_str} ➡️ {new_mode_str}")

                try:
                    from core.alert import send_telegram_alert
                    alert_msg = (
                        f"⚡ **매매방향 자동 스위칭 발동!**\\n"
                        f"----------------------------------------\\n"
                        f"📊 **발동 사유**: {reason_msg}\\n"
                        f"🔄 **모드 전환**: {old_mode_str} ➡️ **{new_mode_str}**\\n"
                        f"⏱ **전환 시각**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
                        f"----------------------------------------\\n"
                        f"💡 대칭 반전 매매가 즉시 적용됩니다."
                    )
                    send_telegram_alert(alert_msg)
                except Exception as ae:
                    logger.error(f"[AUTO MODE SWITCH] 알림 발송 실패: {ae}")
        except Exception as e:
            logger.error(f"[AUTO MODE SWITCH] 오류 발생: {e}")'''

def apply_patch():
    if not os.path.exists(ENGINE_PATH):
        print(f"❌ {ENGINE_PATH} 파일이 없습니다.")
        return False

    with open(ENGINE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if OLD_TARGET not in content:
        print("⚠️ 타겟 패턴을 찾지 못했습니다. 이미 패치되었거나 코드가 다릅니다.")
        if "M == 4:" in content and "초기 4전 중" in content:
            print("✅ 이미 패치가 적용되어 있습니다.")
            return True
        return False

    # 백업
    shutil.copyfile(ENGINE_PATH, BACKUP_PATH)
    print(f"📦 백업 생성 완료: {BACKUP_PATH}")

    new_content = content.replace(OLD_TARGET, NEW_REPLACEMENT, 1)
    with open(ENGINE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("✅ 8403 core/engine.py 패치 완료!")
    return True

if __name__ == "__main__":
    success = apply_patch()
    if not success:
        sys.exit(1)
