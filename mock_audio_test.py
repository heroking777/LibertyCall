#!/usr/bin/env python3
"""
【擬似投入テスト】保存した.rawファイルをGoogleに投げて疎通を証明する
"""

import os
import sys
import time
import logging
from pathlib import Path

# LibertyCallのパスを追加
sys.path.append('/opt/libertycall')

# 【Google認証情報を設定】
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/opt/libertycall/config/google-credentials.json'

from google_stream_asr import GoogleStreamingASR
from gateway.asr.google_asr_config import build_streaming_config, build_recognition_config

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/libertycall/logs/mock_test.log')
    ]
)
logger = logging.getLogger(__name__)

def mock_audio_test():
    """録音データの擬似投入テスト"""
    
    logger.info("=== 【擬似投入テスト】開始 ===")
    
    try:
        # 1. 保存した.rawファイルを読み込む
        raw_file = "/opt/libertycall/audio_recordings/asr_input_20260118_225354_781.raw"
        if not os.path.exists(raw_file):
            logger.error(f"録音ファイルが存在しません: {raw_file}")
            return False
        
        with open(raw_file, "rb") as f:
            audio_data = f.read()
        
        logger.info(f"[MOCK_LOAD] 録音ファイル読み込み完了: {len(audio_data)} bytes")
        logger.info(f"[MOCK_LOAD] ファイルパス: {raw_file}")
        
        # 2. GoogleStreamingASRを初期化
        logger.info("[MOCK_INIT] GoogleStreamingASRを初期化します")
        
        # 設定を構築
        recognition_config = build_recognition_config(
            language_code="ja-JP",
            sample_rate=16000,
            phrase_hints=[]
        )
        streaming_config = build_streaming_config(recognition_config)
        
        # ASRインスタンスを作成（ダミーのAIコア）
        class DummyAICore:
            def _on_asr_error(self, error):
                logger.error(f"[MOCK_ERROR] ASRエラー: {error}")
        
        dummy_core = DummyAICore()
        
        # 【例外処理を外して生のエラーを吐き出す】
        try:
            asr = GoogleStreamingASR(
                language_code="ja-JP",
                sample_rate=16000
            )
            
            logger.info("[MOCK_INIT] ASRインスタンス作成完了")
            
            # 3. ストリーミングを開始
            logger.info("[MOCK_STREAM] ストリーミングを開始します")
            
            # ストリーミングを別スレッドで開始
            import threading
            
            def stream_worker():
                try:
                    asr.start_stream()
                    logger.info("[MOCK_STREAM] ストリーミング開始完了")
                except Exception as e:
                    logger.error(f"[MOCK_STREAM_ERROR] ストリーミング開始エラー: {e}")
                    raise  # 【生のエラーを吐き出す】
            
            stream_thread = threading.Thread(target=stream_worker)
            stream_thread.daemon = True
            stream_thread.start()
            
            # ストリーミングが準備できるのを待つ
            time.sleep(2.0)
            
            # 4. 録音データを擬似投入
            logger.info("[MOCK_FEED] 録音データを擬似投入します")
            
            # データを小分けにして投入（100msごと）
            chunk_size = 3200  # 100ms分
            total_chunks = len(audio_data) // chunk_size
            
            for i in range(total_chunks):
                start_pos = i * chunk_size
                end_pos = start_pos + chunk_size
                chunk = audio_data[start_pos:end_pos]
                
                logger.info(f"[MOCK_CHUNK] チャンク {i+1}/{total_chunks}: {len(chunk)} bytes")
                
                # ASRにデータを投入
                asr.add_audio(chunk)
                
                # 少し待機（リアルタイム性をシミュレート）
                time.sleep(0.1)
            
            # 5. 結果を待機
            logger.info("[MOCK_WAIT] 結果を待機します...")
            
            # 最大10秒待機
            for i in range(100):
                time.sleep(0.1)
                
                # 結果をチェック
                if hasattr(asr, 'result_text') and asr.result_text:
                    logger.info(f"[MOCK_SUCCESS] 認識成功！テキスト: '{asr.result_text}'")
                    return True
                
                # 途中経過を表示
                if i % 20 == 0:  # 2秒ごと
                    logger.info(f"[MOCK_WAIT] 待機中... {i/10:.1f}s/10s")
            
            logger.warning("[MOCK_TIMEOUT] 10秒待っても結果がありません")
            
            # 6. クリーンアップ
            asr.stop()
            logger.info("[MOCK_CLEANUP] クリーンアップ完了")
            
        except Exception as e:
            logger.error(f"[MOCK_EXCEPTION] 予期せぬエラー: {e}")
            import traceback
            logger.error(f"[MOCK_TRACEBACK] {traceback.format_exc()}")
            raise  # 【生のエラーを吐き出す】
        
        return False
        
    except Exception as e:
        logger.error(f"[MOCK_FATAL] 致命的エラー: {e}")
        import traceback
        logger.error(f"[MOCK_FATAL_TRACEBACK] {traceback.format_exc()}")
        raise  # 【生のエラーを吐き出す】

if __name__ == "__main__":
    try:
        success = mock_audio_test()
        if success:
            logger.info("=== 【擬似投入テスト】成功 ===")
            sys.exit(0)
        else:
            logger.error("=== 【擬似投入テスト】失敗 ===")
            sys.exit(1)
    except Exception as e:
        logger.error(f"=== 【擬似投入テスト】例外発生 ===")
        logger.error(f"エラー: {e}")
        import traceback
        logger.error(f"トレースバック: {traceback.format_exc()}")
        sys.exit(2)
