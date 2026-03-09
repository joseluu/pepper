#!/bin/sh
# Start the qi bridge server (Python 2 -> Python 3 bridge)
# Run this before using Python 3 with qi on pepper

SOCKET_PATH="/tmp/qi_bridge.sock"

# Check if already running
if [ -S "$SOCKET_PATH" ]; then
    echo "qi bridge already running at $SOCKET_PATH"
    exit 0
fi

cd /tmp
export LD_LIBRARY_PATH=/opt/aldebaran/lib
export PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages

nohup python2 /data/python3.5/bin/qi_bridge_server.py > /tmp/qi_bridge.log 2>&1 &
echo $! > /tmp/qi_bridge.pid
sleep 1

if [ -S "$SOCKET_PATH" ]; then
    echo "qi bridge server started (PID $(cat /tmp/qi_bridge.pid))"
else
    echo "Failed to start qi bridge server. Check /tmp/qi_bridge.log"
    exit 1
fi
