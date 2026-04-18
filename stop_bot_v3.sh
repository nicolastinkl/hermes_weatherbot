#!/bin/bash
# Stop bot_v3

PID=$(pgrep -f "bot_v3.py run" 2>/dev/null)

if [ -z "$PID" ]; then
    echo "bot_v3 is not running!"
    exit 1
fi

echo "Stopping bot_v3 (PID: $PID)..."
kill $PID

# Wait for process to stop
for i in {1..5}; do
    if ! pgrep -f "bot_v3.py run" > /dev/null 2>&1; then
        echo "bot_v3 stopped successfully!"
        exit 0
    fi
    sleep 1
done

# Force kill if still running
echo "Force killing bot_v3..."
kill -9 $PID 2>/dev/null
echo "bot_v3 stopped!"
