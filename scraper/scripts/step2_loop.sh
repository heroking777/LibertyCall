#!/bin/bash
source /opt/libertycall/scraper/venv/bin/activate
export PYTHONUNBUFFERED=1
while true; do
  for i in $(seq 0 14); do
    python3 /opt/libertycall/scraper/scripts/step2_smtp_guess.py $i 15 &
  done
  wait
  echo "$(date): 全ワーカー完了。5分待機後に再開..."
  sleep 300
done
