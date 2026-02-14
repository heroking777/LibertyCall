#!/usr/bin/env python3
"""StreamingLLMHandlerテスト - 誤認識テキストから正しい応答IDを推測"""
import sys
import time
sys.path.append('/opt/libertycall')

def test_streaming_llm():
    try:
        from gateway.dialogue.streaming_llm_handler import StreamingLLMHandler
        
        print("StreamingLLMHandlerテスト開始...")
        handler = StreamingLLMHandler('whisper_test')
        
        tests = [
            '必要についておしてください',  # 最新の誤認識（「システムについて」の誤認識）
            'いつもいつ行き出をしている',  # 前の誤認識
            'ご視聴ありがとうございました',  # 成功事例
            'しすてむについて',  # 予備
        ]
        
        for text in tests:
            print(f"\nテスト: '{text}'")
            handler.reset()
            handler.add_fragment(text)
            
            # LLM推論を待つ
            print("  LLM推論中...")
            time.sleep(3)
            
            result = handler.finalize()
            print(f"  -> 結果: {result}")
            
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_streaming_llm()
