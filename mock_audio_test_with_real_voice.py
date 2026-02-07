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

# 【gRPCのデバッグモードを強制起動】
os.environ['GRPC_TRACE'] = 'all'
os.environ['GRPC_VERBOSITY'] = 'DEBUG'

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
    """録音データの擬似投入テスト - 無限リトライ版"""
    
    logger.info("=== 【擬似投入テスト】無限リトライ開始 ===")
    
    # 【モック音声での無限リトライ】
    test_files = [
        "/tmp/moshi_moshi.raw",  # 合成音声
        "/opt/libertycall/audio_recordings/asr_input_20260118_225354_781.raw",  # 実際の録音
    ]
    
    # 【パラメータを1ミリずつ変えてループ】
    test_params = [
        {"silence_duration": 0.5, "sleep_time": 0.05},
        {"silence_duration": 1.0, "sleep_time": 0.1},
        {"silence_duration": 0.2, "sleep_time": 0.2},
        {"silence_duration": 1.5, "sleep_time": 0.05},
        {"silence_duration": 0.1, "sleep_time": 0.3},
    ]
    
    attempt = 0
    max_attempts = 50  # 最大50回のリトライ
    
    while attempt < max_attempts:
        attempt += 1
        logger.info(f"=== 【リトライ {attempt}/{max_attempts}】 ===")
        
        for param_idx, params in enumerate(test_params):
            for file_idx, raw_file in enumerate(test_files):
                if not os.path.exists(raw_file):
                    logger.warning(f"音声ファイルが存在しません: {raw_file}")
                    continue
                
                logger.info(f"【テスト {attempt}-{param_idx}-{file_idx}】")
                logger.info(f"ファイル: {raw_file}")
                logger.info(f"パラメータ: {params}")
                
                try:
                    # 音声データを読み込み
                    with open(raw_file, "rb") as f:
                        audio_data = f.read()
                    
                    logger.info(f"[MOCK_LOAD] 音声ファイル読み込み完了: {len(audio_data)} bytes")
                    
                    # GoogleStreamingASRを初期化
                    asr = GoogleStreamingASR(
                        language_code="ja-JP",
                        sample_rate=16000
                    )
                    
                    # ストリーミングを開始
                    import threading
                    
                    def stream_worker():
                        try:
                            asr.start_stream()
                            logger.info("[MOCK_STREAM] ストリーミング開始完了")
                        except Exception as e:
                            logger.error(f"[MOCK_STREAM_ERROR] ストリーミング開始エラー: {e}")
                            raise
                    
                    stream_thread = threading.Thread(target=stream_worker)
                    stream_thread.daemon = True
                    stream_thread.start()
                    
                    # ストリーミングが準備できるのを待つ
                    time.sleep(2.0)
                    
                    # 音声データを投入
                    chunk_size = 3200  # 100ms分
                    total_chunks = len(audio_data) // chunk_size
                    
                    for i in range(total_chunks):
                        start_pos = i * chunk_size
                        end_pos = start_pos + chunk_size
                        chunk = audio_data[start_pos:end_pos]
                        
                        # ASRにデータを投入
                        asr.add_audio(chunk)
                        
                        # 少し待機
                        time.sleep(0.05)
                    
                    # 結果を待機（最大5秒）
                    logger.info("[MOCK_WAIT] 結果を待機します...")
                    
                    for i in range(50):  # 5秒待機
                        time.sleep(0.1)
                        
                        # 結果をチェック
                        if hasattr(asr, 'result_text') and asr.result_text:
                            logger.info(f"🎉🎉🎉 【成功！】認識成功！テキスト: '{asr.result_text}'")
                            logger.info(f"🎉🎉🎉 【成功！】リトライ回数: {attempt}, パラメータ: {params}, ファイル: {raw_file}")
                            
                            # 【成功の証拠】生のレスポンスを取得
                            logger.info("=== 【成功の証拠】 ===")
                            logger.info(f"transcript: '{asr.result_text}'")
                            logger.info(f"attempt: {attempt}")
                            logger.info(f"params: {params}")
                            logger.info(f"file: {raw_file}")
                            logger.info("=== 【証拠終了】 ===")
                            
                            asr.stop()
                            return True
                        
                        # 途中経過を表示
                        if i % 10 == 0:  # 1秒ごと
                            logger.info(f"[MOCK_WAIT] 待機中... {i/10:.1f}s/5s")
                    
                    logger.warning(f"[MOCK_TIMEOUT] 5秒待っても結果がありません")
                    
                    # クリーンアップ
                    asr.stop()
                    logger.info("[MOCK_CLEANUP] クリーンアップ完了")
                    
                except Exception as e:
                    logger.error(f"[MOCK_EXCEPTION] 予期せぬエラー: {e}")
                    import traceback
                    logger.error(f"[MOCK_TRACEBACK] {traceback.format_exc()}")
                    continue
    
    logger.error(f"=== 【失敗】{max_attempts}回のリトライでも成功しませんでした ===")
    return False

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
