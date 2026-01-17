"""
TTS (Text-to-Speech) ユーティリティ関数

Gemini APIを使用した音声合成機能を担当
"""

import logging
from typing import Optional

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ModuleNotFoundError:
    genai = None
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)


def synthesize_text_with_gemini(text: str, speaking_rate: float = 1.0, pitch: float = 0.0) -> Optional[bytes]:
    """
    Gemini APIを使用してテキストから音声を合成する（日本語音声に最適化）
    
    :param text: 音声化するテキスト
    :param speaking_rate: 話す速度（デフォルト: 1.0）
    :param pitch: ピッチ（デフォルト: 0.0）
    :return: 音声データ（bytes）、失敗時はNone
    """
    if not GEMINI_AVAILABLE:
        logger.error("Gemini APIが利用できません")
        return None
    
    if not text or not text.strip():
        logger.warning("音声合成するテキストが空です")
        return None
    
    try:
        # Gemini APIの初期化（環境変数からAPIキーを取得）
        import os
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("GEMINI_API_KEYが設定されていません")
            return None
        
        genai.configure(api_key=api_key)
        
        # モデルの設定（音声合成に対応したモデル）
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # 音声合成リクエストの作成
        # 日本語音声に最適化したパラメータ設定
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 2048,
        }
        
        # プロンプトの構築（日本語音声合成用）
        prompt = f"""
以下の日本語テキストを自然な音声で読み上げてください。話す速度は{speaking_rate}倍、ピッチは{pitch}です。

テキスト: {text}

注意事項:
- 自然な日本語のイントネーションで
- 適切な間合いを入れて
- 感情を込めて読み上げてください
"""
        
        # 音声合成の実行
        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )
        
        # レスポンスから音声データを抽出
        # 注: 実際のGemini APIでは音声データの取得方法が異なる場合があります
        if hasattr(response, 'text'):
            # テキストレスポンスの場合（現行のGemini APIでは音声合成は未サポートの場合あり）
            logger.warning("Gemini APIの現在のバージョンでは音声合成はサポートされていません")
            return None
        else:
            # バイナリデータの場合
            return response.candidates[0].content.parts[0].blob.data
            
    except Exception as e:
        logger.exception(f"音声合成中にエラーが発生しました: {e}")
        return None


def synthesize_template_audio(template_id: str, template_config_func) -> Optional[bytes]:
    """
    テンプレートIDから音声を合成する
    
    :param template_id: テンプレートID
    :param template_config_func: テンプレート設定を取得する関数
    :return: 音声データ（bytes）、失敗時はNone
    """
    config = template_config_func(template_id)
    if not config:
        logger.error(f"テンプレートID {template_id} が見つかりません")
        return None
    
    text = config.get("text", "")
    voice = config.get("voice", "ja-JP-Neural2-B")
    rate = config.get("rate", 1.0)
    
    logger.info(f"テンプレート音声合成: {template_id} -> {text[:50]}...")
    
    return synthesize_text_with_gemini(text, speaking_rate=rate, pitch=0.0)


def synthesize_template_sequence(template_ids: list, template_config_func) -> Optional[bytes]:
    """
    テンプレートシーケンスから連結した音声を合成する
    
    :param template_ids: テンプレートIDのリスト
    :param template_config_func: テンプレート設定を取得する関数
    :return: 連結された音声データ（bytes）、失敗時はNone
    """
    if not template_ids:
        logger.warning("テンプレートIDリストが空です")
        return None
    
    audio_segments = []
    
    for template_id in template_ids:
        audio_data = synthesize_template_audio(template_id, template_config_func)
        if audio_data:
            audio_segments.append(audio_data)
        else:
            logger.error(f"テンプレート {template_id} の音声合成に失敗しました")
            return None
    
    # 音声データを連結
    if audio_segments:
        return b"".join(audio_segments)
    else:
        return None
