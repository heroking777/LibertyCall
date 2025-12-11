#!/bin/bash
# LibertyCall 本番環境変数セット（コピペ用）
# 使用方法: source setup_env.sh

# venv 有効化は環境に合わせて
# source /opt/libertycall/venv/bin/activate

export LC_ASR_PROVIDER="google"
export LC_ASR_STREAMING_ENABLED="1"        # ストリーミング使うなら 1、使わないなら 0

export LC_GOOGLE_PROJECT_ID="libertycall-main"
export LC_GOOGLE_CREDENTIALS_PATH="/opt/libertycall/key/google_tts.json"
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json"

# いつもの起動コマンド
# python gateway/realtime_gateway.py

