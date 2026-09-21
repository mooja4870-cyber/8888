#!/bin/bash
echo "Killing existing bot.py processes..."
pkill -f "python.*bot\.py"
sleep 2

# Core bots to run according to the rule + 8410? 
# Rule says: 8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409 (but 8404 is excluded from dashboard, though it was running)
# Let's start the core ones (8401, 8402, 8407, 8409, 8410) + 8403, 8404, 8405, 8408
for bot in 8401 8402 8403 8404 8405 8407 8408 8409 8410; do
    if [ -d "/Users/l/project/$bot" ]; then
        cd "/Users/l/project/$bot"
        nohup /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python bot.py > bot_output.log 2>&1 &
        echo "Started bot $bot"
    fi
done
