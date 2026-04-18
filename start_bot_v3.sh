#!/bin/bash
# Start bot_v3 in background

cd ~/weatherbot

# Check if already running
if pgrep -f "bot_v3.py run" > /dev/null 2>&1; then
    echo "bot_v3 is already running!"
    pgrep -f "bot_v3.py run" | xargs ps -p
    exit 1
fi

nohup ~/weatherbot/venv/bin/python bot_v3.py run > ~/weatherbot/bot_v3.log 2>&1 &
PID=$!

echo "bot_v3 started with PID: $PID"
echo "Log file: ~/weatherbot/bot_v3.log"
