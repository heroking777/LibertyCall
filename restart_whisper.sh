#!/bin/bash
# Whisper再起動のみ。FreeSWITCHには触らない
pkill -f ws_sink_whisper.py 2>/dev/null
sleep 2
find /opt/libertycall/asr_stream -name "*.pyc" -delete 2>/dev/null
find /opt/libertycall/asr_stream -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
cd /opt/libertycall/asr_stream && WHISPER_MODEL=tiny nohup /opt/libertycall/venv/bin/python3 -u ws_sink_whisper.py > /tmp/whisper_out.txt 2>&1 &
sleep 10
ss -tlnp | grep 8083 && echo "READY - call 05055271174"
