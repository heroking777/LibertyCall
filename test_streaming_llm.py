#!/usr/bin/env python3
"""StreamingLLMHandlerテスト - 誤認識テキストから正しい応答IDを推測"""
import sys
import time
import logging
sys.path.append('/opt/libertycall')

# ログレベルをDEBUGに設定
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_streaming_llm():
    try:
        from gateway.dialogue.llm_handler import LLMDialogueHandler
        from gateway.dialogue.streaming_llm_handler import StreamingLLMHandler
        
        print("StreamingLLMHandlerテスト開始...")
        
        # 先にLLMをロード
        print("LLMをプリロード中...")
        llm_handler = LLMDialogueHandler.get_instance()
        if not llm_handler._ensure_loaded():
            print("LLMロード失敗")
            return
        print("LLMロード完了")
        
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
            time.sleep(5)  # 5秒に延長
            
            # 内部状態を確認
            print(f"  fragments: {handler.fragments}")
            print(f"  best_response_id: {handler.best_response_id}")
            
            result = handler.finalize()
            print(f"  -> 結果: {result}")
            
            # finalize後の状態
            print(f"  finalize後 fragments: {handler.fragments}")
            print(f"  finalize後 best_response_id: {handler.best_response_id}")
            
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_streaming_llm()
