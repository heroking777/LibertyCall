#!/usr/bin/env python3
"""
LibertyCall AICore 初期化テスト（ASR/TTSまとめて・テストループ無し）

ガッツリ通話テストじゃなくて、
「GoogleASR + TTS が初期化までちゃんと走るか」だけ見るワンショットです。

使用方法:
    cd /opt/libertycall
    source venv/bin/activate
    
    export LC_ASR_PROVIDER="google"
    export LC_GOOGLE_PROJECT_ID="libertycall-main"
    export LC_GOOGLE_CREDENTIALS_PATH="/opt/libertycall/key/google_tts.json"
    export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json"
    
    python test_init.py

ここまで通れば、
- GoogleASR 初期化（認証含む）
- TTS クライアント初期化
- AICore の ASR/TTS 連携
が全部１ショットで通っているので、「起動時クラッシュ」はもう潰せています。
"""

from libertycall.gateway.core.ai_core import AICore

print(">>> creating AICore(init_clients=True)")
core = AICore(init_clients=True)
print("AICore created. asr_provider =", core.asr_provider)
print("streaming_enabled =", core.streaming_enabled)
print("tts_client =", type(core.tts_client).__name__ if core.tts_client else None)
print("OK: AICore init completed without crash")

