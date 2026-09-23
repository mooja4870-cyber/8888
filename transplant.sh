#!/bin/bash
for b in 8404 8406 8408; do
  echo "Transplanting 8410 to $b..."
  # Kill the running bot first!
  cd /Users/l/project/$b
  ./run_bot.sh stop 2>/dev/null || pkill -f "$b"
  sleep 1
  
  # Rsync
  rsync -av --delete \
    --exclude='.env' \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='run.sh' \
    --exclude='*.log' \
    --exclude='*.bak*' \
    --exclude='*.pid' \
    --exclude='data' \
    --exclude='__pycache__' \
    /Users/l/project/8410/ /Users/l/project/$b/
    
  echo "Transplant to $b complete. Restarting..."
  # Now restart the bot
  bash run.sh
done
