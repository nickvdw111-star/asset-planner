#!/usr/bin/env bash
set -e

PIDFILE="/tmp/printmap-dev.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
  echo "Already running (PID $(cat $PIDFILE)). Run './dev.sh stop' to stop it."
  exit 1
fi

if [ "$1" = "stop" ]; then
  if [ -f "$PIDFILE" ]; then
    kill "$(cat $PIDFILE)" && rm "$PIDFILE" && echo "Stopped."
  else
    echo "Not running."
  fi
  exit 0
fi

cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true

export DATA_DIR="$(pwd)/data"
echo "Starting PrintMap dev server on :5050 (data: $DATA_DIR)..."
python3 app.py &
echo $! > "$PIDFILE"
echo "PID $(cat $PIDFILE). Stop with: ./dev.sh stop"
