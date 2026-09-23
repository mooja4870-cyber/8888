import os

def process_engine_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if "async def _check_closed_positions_async(self, record_only: bool = False):" in line:
            start_idx = i
        elif start_idx != -1 and "async def _run_position_rotation_check_async" in line:
            end_idx = i
            break
            
    if start_idx == -1 or end_idx == -1:
        print(f"[{filepath}] Method bounds not found")
        return False
        
    original_block = lines[start_idx:end_idx]
    
    # We will build three new methods.
    
    # 1. sync block (from start_idx to before "if not record_only and getattr(self.cfg, 'MAX_HOLDING_HOURS', 0)")
    # Also we need to find where "if self._prev_position_symbols != current:" is.
    
    timeout_start = -1
    state_save_start = -1
    state_save_end = -1
    
    for i, line in enumerate(original_block):
        if "if not record_only and getattr(self.cfg, \"MAX_HOLDING_HOURS\", 0) > 0:" in line or "if not record_only and self.cfg.MAX_HOLDING_HOURS > 0:" in line or "# --- [HARD SL/TP GUARD]" in line:
            if timeout_start == -1:
                timeout_start = i
        
        if "if self._prev_position_symbols != current:" in line:
            state_save_start = i
            
        if "if record_only:" in line and state_save_start != -1:
            state_save_end = i
            
    if timeout_start == -1 or state_save_start == -1 or state_save_end == -1:
        print(f"[{filepath}] Sub-blocks not found. timeout={timeout_start}, state_save={state_save_start}")
        return False
        
    # The sync logic is:
    # Top part (0 to timeout_start)
    sync_part1 = original_block[1:timeout_start] # exclude the def line
    # Bottom part (state_save_start to state_save_end)
    sync_part2 = original_block[state_save_start:state_save_end]
    
    sync_method = ["    async def _sync_closed_positions_from_exchange(self, raw_positions):\n"] + sync_part1 + sync_part2
    
    # The smart exit logic is:
    # timeout_start to state_save_start
    smart_part1 = original_block[timeout_start:state_save_start]
    # after state_save_end (excluding "if record_only: return")
    # Actually, the "if record_only:" and "return" take 2 lines.
    smart_part2 = original_block[state_save_end+2:] # +2 skips "if record_only:\n", "    return\n"
    
    smart_method = ["\n    async def _evaluate_smart_exits(self, raw_positions):\n"] + smart_part1 + smart_part2
    
    # Clean up "if not record_only and " in smart_method
    for i in range(len(smart_method)):
        smart_method[i] = smart_method[i].replace("if not record_only and ", "if ")
        smart_method[i] = smart_method[i].replace("if not record_only:", "if True:")
    
    # The new wrapper method
    wrapper_method = [
        "\n    async def _check_closed_positions_async(self, record_only: bool = False):\n",
        "        \"\"\"기존 함수 호환성 유지용 래퍼 (Wrapper)\"\"\"\n",
        "        if not self.is_ready:\n",
        "            return\n",
        "        try:\n",
        "            raw_positions = await self._maybe_await(self.client.get_positions())\n",
        "            \n",
        "            # 1. 장부 기록 로직은 무조건 실행\n",
        "            await self._sync_closed_positions_from_exchange(raw_positions)\n",
        "            \n",
        "            # 2. 스마트 매매 로직은 record_only가 아닐 때만 실행\n",
        "            if not record_only:\n",
        "                await self._evaluate_smart_exits(raw_positions)\n",
        "                \n",
        "        except Exception as e:\n",
        "            logger.error(f\"청산 감지 오류: {e}\")\n\n"
    ]
    
    new_lines = lines[:start_idx] + sync_method + smart_method + wrapper_method + lines[end_idx:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print(f"[{filepath}] Refactored successfully.")
    return True

for i in range(8401, 8411):
    process_engine_file(f"/Users/l/project/{i}/core/engine.py")

