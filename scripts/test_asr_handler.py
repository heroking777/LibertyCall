#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASRハンドラーのテストスクリプト

FreeSWITCH ESL接続とGoogle Streaming ASRの動作確認を行う
"""

import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def test_esl_connection():
    """FreeSWITCH ESL接続テスト"""
    logger.info("=" * 60)
    logger.info("1. FreeSWITCH ESL接続テスト")
    logger.info("=" * 60)
    
    try:
        from libs.esl.ESL import ESLconnection
        
        esl_host = "127.0.0.1"
        esl_port = 8021
        esl_password = "ClueCon"
        
        logger.info(f"接続中: {esl_host}:{esl_port}")
        con = ESLconnection(esl_host, esl_port, esl_password)
        
        if not con.connected():
            logger.error("❌ ESL接続失敗")
            logger.error("確認: sudo netstat -tulnp | grep 8021")
            logger.error("確認: sudo systemctl status freeswitch")
            return False
        
        logger.info("✅ ESL接続成功")
        
        # ステータス確認
        try:
            status = con.api("status")
            if status:
                logger.info("✅ FreeSWITCH API応答正常")
                logger.debug(f"ステータス: {status.getBody()[:200] if hasattr(status, 'getBody') else 'N/A'}")
        except Exception as e:
            logger.warning(f"ステータス取得エラー（非致命的）: {e}")
        
        con.disconnect()
        return True
        
    except ImportError:
        logger.error("❌ ESLモジュールが見つかりません")
        logger.error("確認: libs/esl/ESL.py が存在するか確認してください")
        return False
    except Exception as e:
        logger.error(f"❌ ESL接続エラー: {e}", exc_info=True)
        return False


def test_google_credentials():
    """Google Cloud認証情報テスト"""
    logger.info("=" * 60)
    logger.info("2. Google Cloud認証情報テスト")
    logger.info("=" * 60)
    
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if not cred_path:
        logger.error("❌ GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていません")
        logger.info("設定例: export GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json")
        return False
    
    cred_file = Path(cred_path)
    
    if not cred_file.exists():
        logger.error(f"❌ 認証ファイルが見つかりません: {cred_path}")
        return False
    
    logger.info(f"✅ 認証ファイル存在確認: {cred_path}")
    
    # Google Cloud Speech APIのインポートテスト
    try:
        from google.cloud import speech
        logger.info("✅ google-cloud-speech モジュール読み込み成功")
        
        # クライアント初期化テスト
        try:
            client = speech.SpeechClient()
            logger.info("✅ Google Speech Client初期化成功")
            return True
        except Exception as e:
            logger.error(f"❌ Google Speech Client初期化失敗: {e}")
            logger.error("確認: 認証ファイルの内容が正しいか確認してください")
            return False
            
    except ImportError:
        logger.error("❌ google-cloud-speech モジュールが見つかりません")
        logger.error("インストール: pip install google-cloud-speech")
        return False


def test_asr_handler_import():
    """ASRハンドラーモジュールのインポートテスト"""
    logger.info("=" * 60)
    logger.info("3. ASRハンドラーモジュールテスト")
    logger.info("=" * 60)
    
    try:
        from asr_handler import ASRHandler, get_or_create_handler, remove_handler
        from google_stream_asr import GoogleStreamingASR
        
        logger.info("✅ asr_handler モジュール読み込み成功")
        logger.info("✅ google_stream_asr モジュール読み込み成功")
        
        # クラス初期化テスト（実際の接続は行わない）
        try:
            # テスト用のcall_id
            test_call_id = "test-uuid-12345"
            handler = ASRHandler(test_call_id)
            logger.info(f"✅ ASRHandler初期化成功 (call_id={test_call_id})")
            
            # クリーンアップ
            handler.stop()
            remove_handler(test_call_id)
            
            return True
        except Exception as e:
            logger.error(f"❌ ASRHandler初期化失敗: {e}", exc_info=True)
            return False
            
    except ImportError as e:
        logger.error(f"❌ モジュールインポート失敗: {e}")
        return False


def test_audio_files():
    """音声ファイルの存在確認"""
    logger.info("=" * 60)
    logger.info("4. 音声ファイル存在確認")
    logger.info("=" * 60)
    
    audio_dir = Path("/opt/libertycall/clients/000/audio")
    required_files = [
        "000_8k.wav",
        "001_8k.wav",
        "002_8k.wav",
        "000-004_8k.wav",
        "000-005_8k.wav",
        "000-006_8k.wav"
    ]
    
    all_exist = True
    
    for filename in required_files:
        file_path = audio_dir / filename
        if file_path.exists():
            size = file_path.stat().st_size
            logger.info(f"✅ {filename} ({size:,} bytes)")
        else:
            logger.error(f"❌ {filename} が見つかりません")
            all_exist = False
    
    return all_exist


def main():
    """メインテスト実行"""
    logger.info("=" * 60)
    logger.info("ASRハンドラーテスト開始")
    logger.info("=" * 60)
    
    results = []
    
    # テスト実行
    results.append(("ESL接続", test_esl_connection()))
    results.append(("Google認証", test_google_credentials()))
    results.append(("ASRハンドラー", test_asr_handler_import()))
    results.append(("音声ファイル", test_audio_files()))
    
    # 結果サマリー
    logger.info("=" * 60)
    logger.info("テスト結果サマリー")
    logger.info("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")
        if not result:
            all_passed = False
    
    logger.info("=" * 60)
    if all_passed:
        logger.info("✅ すべてのテストが成功しました")
        logger.info("次のステップ: 着信テストを実行してください")
        return 0
    else:
        logger.error("❌ 一部のテストが失敗しました")
        logger.error("上記のエラーメッセージを確認して修正してください")
        return 1


if __name__ == "__main__":
    sys.exit(main())

