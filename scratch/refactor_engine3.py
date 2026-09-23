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
        return False
        
    original_block = lines[start_idx:end_idx]
    
    # Exclude the trailing 'except' block from original_block
    except_idx = -1
    for i in range(len(original_block)-1, -1, -1):
        if "except Exception as e:" in original_block[i]:
            except_idx = i
            break
            
    if except_idx != -1:
        # cut off the except block and everything after it
        original_block = original_block[:except_idx]
        
    timeout_start = -1
    state_save_start = -1
    state_save_end = -1
    try_idx = -1
    
    for i, line in enumerate(original_block):
        if line.strip() == "try:":
            try_idx = i
        if "if not record_only and getattr(self.cfg, \"MAX_HOLDING_HOURS\", 0) > 0:" in line or "if not record_only and self.cfg.MAX_HOLDING_HOURS > 0:" in line or "# --- [HARD SL/TP GUARD]" in line:
            if timeout_start == -1:
                timeout_start = i
        
        if "if self._prev_position_symbols != current:" in line:
            state_save_start = i
            
        if "if record_only:" in line and state_save_start != -1:
            state_save_end = i
            
    if timeout_start == -1 or state_save_start == -1 or state_save_end == -1 or try_idx == -1:
        print(f"[{filepath}] sub-blocks not found")
        return False
        
    # We will remove the 'try:' line completely and unindent everything below it by 4 spaces
    # Wait, the lines before 'try:' (e.g. `if not self.is_ready: return`) should be in the wrapper, NOT in sync_method.
    # Let's put everything from `try_idx + 1` up to `timeout_start` into sync_method, unindented.
    
    def unindent(block):
        return [line[4:] if line.startswith("    ") else line for line in block]
        
    sync_part1 = unindent(original_block[try_idx+1:timeout_start])
    sync_part2 = unindent(original_block[state_save_start:state_save_end])
    
    sync_method = ["    async def _sync_closed_positions_from_exchange(self, raw_positions):\n"] + sync_part1 + sync_part2
    
    smart_part1 = unindent(original_block[timeout_start:state_save_start])
    smart_part2 = unindent(original_block[state_save_end+2:]) # skip if record_only: return
    
    smart_method = ["\n    async def _evaluate_smart_exits(self, raw_positions):\n"] + smart_part1 + smart_part2
    
    for i in range(len(smart_method)):
        smart_method[i] = smart_method[i].replace("if not record_only and ", "if ")
        smart_method[i] = smart_method[i].replace("if not record_only:\n", "if True:\n")
        
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

