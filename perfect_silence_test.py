#!/usr/bin/env python3
"""
【完璧な無音テスト】プログラム内で完璧な16kHz/16bit/Monoの無音を生成して投げる
"""

import os
import sys
import time
import logging
import numpy as np

# LibertyCallのパスを追加
sys.path.append('/opt/libertycall')

# 【Google認証情報を設定】
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/opt/libertycall/config/google-credentials.json'

# 【gRPCのデバッグモードを強制起動】
os.environ['GRPC_TRACE'] = 'all'
os.environ['GRPC_VERBOSITY'] = 'DEBUG'

from google_stream_asr import GoogleStreamingASR

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/libertycall/logs/perfect_silence_test.log')
    ]
)
logger = logging.getLogger(__name__)

def perfect_silence_test():
    """完璧な無音テスト"""
    
    logger.info("=== 【完璧な無音テスト】開始 ===")
    
    try:
        # GoogleStreamingASRを初期化
        logger.info("[SILENCE_INIT] GoogleStreamingASRを初期化します")
        
        asr = GoogleStreamingASR(
            language_code="ja-JP",
            sample_rate=16000
        )
        
        logger.info("[SILENCE_INIT] ASRインスタンス作成完了")
        
        # ストリーミングを開始
        logger.info("[SILENCE_STREAM] ストリーミングを開始します")
        
        import threading
        
        def stream_worker():
            try:
                asr.start_stream()
                logger.info("[SILENCE_STREAM] ストリーミング開始完了")
            except Exception as e:
                logger.error(f"[SILENCE_STREAM_ERROR] ストリーミング開始エラー: {e}")
                raise
        
        stream_thread = threading.Thread(target=stream_worker)
        stream_thread.daemon = True
        stream_thread.start()
        
        # ストリーミングが準備できるのを待つ
        logger.info("[SILENCE_WAIT] ストリーミング準備を待機します...")
        time.sleep(2.0)
        
        # 【完璧な無音データを生成】
        silence_duration = 2.0  # 2秒の無音
        sample_rate = 16000  # 16kHz
        bytes_per_sample = 2  # 16bit
        
        silence_size = int(silence_duration * sample_rate * bytes_per_sample)
        silence_data = b'\x00\x00' * (silence_size // 2)
        
        logger.info(f"[SILENCE_GENERATE] 完璧な無音を生成: {silence_size} bytes ({silence_duration}s)")
        logger.info(f"[SILENCE_PATTERN] 無音データパターン: {silence_data[:20].hex()}...")
        
        # 無音データを投入
        logger.info("[SILENCE_FEED] 無音データを投入します")
        
        # 100msごとに分割して投入
        chunk_size = 3200  # 100ms分
        total_chunks = len(silence_data) // chunk_size
        
        for i in range(total_chunks):
            start_pos = i * chunk_size
            end_pos = start_pos + chunk_size
            chunk = silence_data[start_pos:end_pos]
            
            logger.info(f"[SILENCE_CHUNK] チャンク {i+1}/{total_chunks}: {len(chunk)} bytes")
            
            # ASRにデータを投入
            asr.add_audio(chunk)
            
            # 少し待機
            time.sleep(0.1)
        
        # 結果を待機
        logger.info("[SILENCE_WAIT] 結果を待機します...")
        
        # 最大10秒待機
        for i in range(100):
            time.sleep(0.1)
            
            # 結果をチェック
            if hasattr(asr, 'result_text') and asr.result_text:
                logger.info(f"🎉🎉🎉 【成功！】認識成功！テキスト: '{asr.result_text}'")
                logger.info("🎉🎉🎉 【成功！】完璧な無音で応答を取得しました！")
                
                # 【成功の証拠】生のレスポンスを取得
                logger.info("=== 【成功の証拠】 ===")
                logger.info(f"transcript: '{asr.result_text}'")
                logger.info("test_type: perfect_silence")
                logger.info("data_source: program_generated")
                logger.info("=== 【証拠終了】 ===")
                
                asr.stop()
                return True
            
            # 途中経過を表示
            if i % 20 == 0:  # 2秒ごと
                logger.info(f"[SILENCE_WAIT] 待機中... {i/10:.1f}s/10s")
        
        logger.warning("[SILENCE_TIMEOUT] 10秒待っても結果がありません")
        
        # クリーンアップ
        asr.stop()
        logger.info("[SILENCE_CLEANUP] クリーンアップ完了")
        
        return False
        
    except Exception as e:
        logger.error(f"[SILENCE_EXCEPTION] 予期せぬエラー: {e}")
        import traceback
        logger.error(f"[SILENCE_TRACEBACK] {traceback.format_exc()}")
        raise

if __name__ == "__main__":
    try:
        success = perfect_silence_test()
        if success:
            logger.info("=== 【完璧な無音テスト】成功 ===")
            sys.exit(0)
        else:
            logger.error("=== 【完璧な無音テスト】失敗 ===")
            sys.exit(1)
    except Exception as e:
        logger.error(f"=== 【完璧な無音テスト】例外発生 ===")
        logger.error(f"エラー: {e}")
        import traceback
        logger.error(f"トレースバック: {traceback.format_exc()}")
        sys.exit(2)
