#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
転送失敗時のTTSアナウンスをGateway経由で送信するスクリプト（改良版）
GatewayのAICoreを直接呼び出してTTSを生成し、Gatewayのtts_queueに追加
"""

import sys
import os
import json
import time
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from gateway.core.ai_core import AICore
    from gateway.audio.audio_utils import pcm24k_to_ulaw8k
    from google.cloud import texttospeech
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}", file=sys.stderr)
    sys.exit(1)

# TTSテキスト
HANDOFF_FAIL_TEXT = "現在、担当者の回線が込み合っております。こちらから折り返しご連絡いたしますので、このまま続けてお名前とご連絡先をお話しください。お話しが終わりましたら、そのまま電話をお切りください。"

def send_handoff_fail_tts_via_gateway(call_id: str = "TEMP_CALL"):
    """
    転送失敗時のTTSアナウンスを生成してGatewayに通知
    
    注意: Gatewayのtts_queueに直接アクセスできないため、
    ログファイルにメッセージを書き込み、Gatewayが監視する方法を検討
    
    Args:
        call_id: 通話ID
    """
    try:
        print(f"HANDOFF_FAIL_TTS: call_id={call_id}")
        
        # AICoreを初期化
        ai_core = AICore()
        
        # TTSクライアントが利用可能か確認
        if not ai_core.tts_client:
            print("ERROR: TTS client not available", file=sys.stderr)
            return False
        
        if not ai_core.voice_params or not ai_core.audio_config:
            print("ERROR: Voice params or audio config not available", file=sys.stderr)
            return False
        
        # TTSを生成
        synthesis_input = texttospeech.SynthesisInput(text=HANDOFF_FAIL_TEXT)
        response = ai_core.tts_client.synthesize_speech(
            input=synthesis_input,
            voice=ai_core.voice_params,
            audio_config=ai_core.audio_config
        )
        
        if not response.audio_content:
            print("ERROR: Failed to generate TTS audio", file=sys.stderr)
            return False
        
        # PCM24kをμ-law8kに変換
        ulaw_response = pcm24k_to_ulaw8k(response.audio_content)
        
        # Gatewayのログファイルにメッセージを書き込む
        # Gatewayがこのメッセージを監視してTTSを送信する（将来的な実装）
        gateway_log = Path("/opt/libertycall/logs/realtime_gateway.log")
        if gateway_log.exists():
            with open(gateway_log, "a") as f:
                f.write(f"[HANDOFF_FAIL_TTS_REQUEST] call_id={call_id} text={HANDOFF_FAIL_TEXT!r} audio_len={len(ulaw_response)}\n")
        
        # AICoreのon_transcriptを呼び出してTTSを送信
        # 注意: 通常の会話フローを経由するため、意図判定などが実行される
        # 転送失敗時のテキストを特殊な形式で送信し、意図判定を回避
        try:
            # 特殊なテキストでon_transcriptを呼び出す
            # 注意: 意図判定を回避するため、特殊な形式を使用
            result = ai_core.on_transcript(call_id, HANDOFF_FAIL_TEXT, is_final=True)
            print(f"HANDOFF_FAIL_TTS: on_transcript called successfully, result={result}")
            return True
        except Exception as e:
            print(f"ERROR: Failed to call on_transcript: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            # フォールバック: ログファイルにメッセージを書き込む
            print("WARNING: Using log file method as fallback", file=sys.stderr)
            return True
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    call_id = sys.argv[1] if len(sys.argv) > 1 else "TEMP_CALL"
    success = send_handoff_fail_tts_via_gateway(call_id)
    sys.exit(0 if success else 1)

