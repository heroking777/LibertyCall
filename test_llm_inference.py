#!/usr/bin/env python3
"""LLM推論テスト - 誤認識テキストから正しい応答IDを推測できるか"""
import sys
import os
sys.path.append('/opt/libertycall')

def test_llm_inference():
    try:
        from gateway.dialogue.llm_handler import LLMDialogueHandler
        
        print("LLMハンドラを初期化中...")
        handler = LLMDialogueHandler.get_instance()
        
        if not handler._ensure_loaded():
            print("LLMのロードに失敗しました")
            return
        
        print("LLM推論テスト開始...")
        tests = [
            '必要についておしてください',  # 最新の誤認識
            'いつもいつ行き出をしている',  # 前の誤認識
            'ご視聴ありがとうございました',  # 成功事例
            'しすてむについて',  # 予備
        ]
        
        for text in tests:
            print(f"\nテスト: '{text}'")
            try:
                result = handler.get_response(text, 'whisper_test')
                print(f"  -> 結果: {result}")
            except Exception as e:
                print(f"  -> エラー: {e}")
                
    except Exception as e:
        print(f"初期化エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_llm_inference()
