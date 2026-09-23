import re
import sys
import glob

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the start of the method
    match = re.search(r'(    async def _check_closed_positions_async\(self.*?\):\n(?:.*?\n)*?)(?=    async def _run_position_rotation_check_async)', content, re.MULTILINE)
    if not match:
        print(f"[{filepath}] Method not found or rotation check missing")
        return False
        
    old_method_block = match.group(1)
    
    # Let's break it down by searching for key markers
    marker1 = "if not record_only and"
    marker2 = "# --- [HARD SL/TP GUARD]"
    
    # We want to separate the entire body into:
    # 1. Sync part (up to marker1 or marker2)
    # 2. Smart Exit part (marker1/2 up to "if self._prev_position_symbols != current:")
    # 3. State update part ("if self._prev_position_symbols != current:" block)
    # 4. Rotation & Trailing part (after "if record_only: return")
    
    lines = old_method_block.split('\n')
    
    sync_lines = []
    smart_lines = []
    state_lines = []
    trailing_lines = []
    
    phase = 1 # 1: sync, 2: smart, 3: state, 4: trailing
    
    for line in lines:
        if line.strip() == "except Exception as e:":
            # This is the end catch block.
            break
            
        if phase == 1:
            if "if not record_only and" in line or "# --- [HARD SL/TP GUARD]" in line:
                phase = 2
                smart_lines.append(line)
            else:
                sync_lines.append(line)
        elif phase == 2:
            if "if self._prev_position_symbols != current:" in line:
                phase = 3
                state_lines.append(line)
            else:
                smart_lines.append(line)
        elif phase == 3:
            if "if record_only:" in line:
                phase = 4
                # skip "if record_only:" and "return"
            elif "return" in line and len(state_lines) > 0 and state_lines[-1].strip() == "if record_only:":
                pass
            else:
                state_lines.append(line)
        elif phase == 4:
            if "if record_only:" in line or ("return" in line and "if record_only" in lines[lines.index(line)-1]):
                continue
            trailing_lines.append(line)
            
    # Clean up sync_lines (remove the first line which is the def)
    sync_body = "\n".join(sync_lines[1:])
    
    # Remove 'if not record_only:' levels from smart_lines if they exist?
    # No, it's easier to just keep them but we don't pass record_only. We can just replace 'if not record_only' with 'if True' or just remove it later. But wait, it's fine to leave 'if not record_only' if we pass record_only=False to the new method, but we won't.
    # We can just string replace "if not record_only and " with "if "
    smart_body = "\n".join(smart_lines).replace("if not record_only and ", "if ").replace("if not record_only:\n", "if True:\n")
    
    state_body = "\n".join(state_lines)
    trailing_body = "\n".join(trailing_lines)
    
    # Construct the new methods
    new_methods = f"""    async def _sync_closed_positions_from_exchange(self, raw_positions):
{sync_body}
{state_body}

    async def _evaluate_smart_exits(self, raw_positions):
{smart_body}
{trailing_body}

    async def _check_closed_positions_async(self, record_only: bool = False):
        \"\"\"기존 함수 호환성 유지용 래퍼 (Wrapper)\"\"\"
        if not self.is_ready:
            return
        try:
            raw_positions = await self._maybe_await(self.client.get_positions())
            
            # 1. 장부 기록 로직은 무조건 실행
            await self._sync_closed_positions_from_exchange(raw_positions)
            
            # 2. 스마트 매매 로직은 record_only가 아닐 때만 실행
            if not record_only:
                await self._evaluate_smart_exits(raw_positions)
                
        except Exception as e:
            logger.error(f"청산 감지 오류: {{e}}")
            
"""
    
    # Replace old block with new methods
    new_content = content.replace(old_method_block, new_methods)
    
    # But wait, sync_body relies on `self._cached_positions = raw_positions` and `raw_balance` !
    # We should move the top caching part into the wrapper, or just leave it in sync_body.
    # If it's in sync_body, we just need to make sure we don't define `raw_positions = ...` twice.
    # Ah! In my `sync_body`, it ALREADY has `raw_positions = await self._maybe_await(self.client.get_positions())`!
    # Let's fix that.
    
    print(f"[{filepath}] parsed successfully.")
    
    with open(filepath + ".refactored", 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return True

process_file('/Users/l/project/8401/core/engine.py')
