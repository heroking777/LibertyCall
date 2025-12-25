#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.0/2.5 APIを使用した日本語TTS（音声合成）スクリプト

google-generativeaiパッケージとspeech_configを使用して音声を生成します。

voice_list_000.tsvから000-003の音声ファイルを生成します。

使い方:
    export GOOGLE_API_KEY="your-api-key"
    # または
    export GEMINI_API_KEY="your-api-key"
    
    python scripts/generate_gemini_tts.py

生成されるファイル:
    - clients/000/audio/000.wav
    - clients/000/audio/001.wav
    - clients/000/audio/002.wav
    - clients/000/audio/003.wav

依存パッケージ:
    - google-genai: pip install google-genai
"""

import os
import sys
import wave
import io
import base64
from pathlib import Path
from typing import Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("エラー: google-genai がインストールされていません。")
    print("インストール: pip install google-genai")

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"
OUTPUT_DIR = CLIENT_DIR / "audio"

# TTS設定
SAMPLE_RATE = 24000  # 24kHz
BIT_DEPTH = 16  # 16bit
CHANNELS = 1  # モノラル

# Gemini 2.0/2.5 モデル名
# TTS専用モデルを使用（音声生成に特化）
GEMINI_MODEL = "gemini-2.5-flash-preview-tts"

# 音声名（日本語対応）
VOICE_NAME = "Aoede"  # 固定: 一貫した声質を保つため

# ============================================================================
# システムプロンプト（クライアント000専用 - 確定版）
# ============================================================================
# 注意: 将来的にはクライアントごとに異なるプロンプトを設定できるように
#       拡張する予定です（例: CLIENT_PROMPTS = {"000": "...", "001": "..."}）
# ============================================================================
# クライアント000の音声生成では、毎回このプロンプトを使用します。
# Pitch: +2.0, Rate: 1.05 の設定を数値として明示的にプロンプトに含めています。
# ============================================================================
SYSTEM_PROMPT = """[設定: あなたはリバティーコールのプロの女性受付です。以下の『音声物理パラメーター』を厳守して読み上げてください。
・声の高さ(Pitch): +2.0 (標準より高め)
・話速(Rate): 1.05 (標準よりわずかに速く)
・トーン: 明るく、一貫性を保つこと]

読み上げるセリフ："""


def check_credentials() -> bool:
    """認証情報の確認"""
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if not google_api_key and not google_creds:
        print("エラー: 認証情報が設定されていません。")
        print("以下のいずれかを設定してください:")
        print("  export GOOGLE_API_KEY=\"your-api-key\"")
        print("  または")
        print("  export GEMINI_API_KEY=\"your-api-key\"")
        print("  または")
        print("  export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/credentials.json\"")
        return False
    return True


def ensure_directories():
    """必要なディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ確認: {OUTPUT_DIR}")


def load_voice_list(skip_existing: bool = False) -> dict:
    """
    voice_list_000.tsvから音声テキストを読み込む
    
    Args:
        skip_existing: Trueの場合、既に生成済みのファイルをスキップ
    
    Returns:
        音声テキストの辞書 {audio_id: text}
    """
    voice_texts = {}
    
    if not TSV_FILE.exists():
        print(f"エラー: {TSV_FILE} が見つかりません。")
        sys.exit(1)
    
    with open(TSV_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t', 1)
            if len(parts) == 2:
                audio_id = parts[0].strip()
                text = parts[1].strip()
                
                # 000は除外（完成しているため）
                if audio_id == "000":
                    continue
                
                # 既存ファイルをスキップする場合
                if skip_existing:
                    output_wav = OUTPUT_DIR / f"{audio_id}.wav"
                    if output_wav.exists() and output_wav.stat().st_size > 0:
                        continue
                
                voice_texts[audio_id] = text
    
    return voice_texts


def synthesize_with_gemini(text: str, api_key: str, max_retries: int = 3) -> Optional[bytes]:
    """
    Gemini APIを使用してテキストから音声を合成する（google-genaiパッケージ使用）
    
    Args:
        text: 音声化するテキスト
        api_key: APIキー
        max_retries: 最大リトライ回数
    
    Returns:
        音声データ（bytes）または None
    """
    import time
    
    for attempt in range(1, max_retries + 1):
        try:
            if not GENAI_AVAILABLE:
                print("エラー: google-genai がインストールされていません。")
                return None
            
            # クライアントの初期化
            client = genai.Client(api_key=api_key)
            
            # システムプロンプトを固定して一貫した声質を保つ
            prompt = f"{SYSTEM_PROMPT} {text}"
            
            # 生成リクエスト
            # Gemini 2.0 Flash は 'AUDIO' モダリティを指定する必要があります
            # 注意: SpeechConfigにはpitch/speaking_rateパラメータがサポートされていないため、
            # プロンプト内で数値として明示的に指示しています（Pitch: +2.0, Rate: 1.05）
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    responseModalities=["AUDIO"],  # これが最重要（大文字、キャメルケース）
                    temperature=0.0,  # AIの演技の「ゆらぎ」を最小限に抑える
                    speechConfig=types.SpeechConfig(
                        voiceConfig=types.VoiceConfig(
                            prebuiltVoiceConfig=types.PrebuiltVoiceConfig(
                                voiceName=VOICE_NAME
                            )
                        )
                    )
                )
            )
            
            # 音声データの取り出し
            # ユーザー提供のコード例に基づく実装
            # response.candidates[0].content.parts から inline_data を持つ part を探す
            audio_data = None
            
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and candidate.content is not None:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        # inline_dataを持つpartを探す
                        audio_part = next(
                            (part for part in candidate.content.parts if hasattr(part, 'inline_data') and part.inline_data is not None),
                            None
                        )
                        
                        if audio_part:
                            audio_data = audio_part.inline_data.data
                            if audio_data and len(audio_data) > 0:
                                # Base64エンコードされている場合はデコード
                                if isinstance(audio_data, str):
                                    return base64.b64decode(audio_data)
                                return audio_data
            
            # response.partsからも確認（以前の成功時はこちらにあった）
            if not audio_data and hasattr(response, 'parts') and response.parts:
                for part in response.parts:
                    if hasattr(part, 'inline_data') and part.inline_data is not None:
                        audio_data = part.inline_data.data
                        if audio_data and len(audio_data) > 0:
                            # Base64エンコードされている場合はデコード
                            if isinstance(audio_data, str):
                                return base64.b64decode(audio_data)
                            return audio_data
            
            # 音声データが空の場合はリトライ
            if not audio_data or len(audio_data) == 0:
                if attempt < max_retries:
                    print(f"  警告: 音声データが空でした。リトライ {attempt + 1}/{max_retries}...", flush=True)
                    time.sleep(5)  # レート制限回避
                    continue
                else:
                    print(f"警告: 音声データが見つかりませんでした（最大リトライ回数に達しました）。", flush=True)
                    return None
                    
        except Exception as e:
            if attempt < max_retries:
                print(f"  エラー: {e}。リトライ {attempt + 1}/{max_retries}...", flush=True)
                time.sleep(5)  # レート制限回避
                continue
            else:
                print(f"エラー: Gemini API音声合成に失敗しました: {e}", flush=True)
                import traceback
                traceback.print_exc()
                return None
    
    return None


def convert_to_wav(audio_data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    音声データをWAV形式に変換する
    
    Args:
        audio_data: 元の音声データ（PCMまたはWAV）
        sample_rate: サンプリングレート
    
    Returns:
        WAV形式の音声データ
    """
    # 音声データがすでにWAV形式の場合はそのまま返す
    if audio_data[:4] == b'RIFF':
        return audio_data
    
    # PCMデータの場合は、WAVヘッダーを付けて変換
    # Gemini APIから返ってくるデータは生のPCMデータ（16bit、24kHz、モノラル）
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BIT_DEPTH // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)
    
    return wav_buffer.getvalue()


def generate_audio_file(audio_id: str, text: str, api_key: str, sleep_seconds: float = 0.0) -> bool:
    """
    Gemini APIを使用して音声ファイルを生成
    
    Args:
        audio_id: 音声ID（例: "000"）
        text: 音声化するテキスト
        api_key: APIキー
    
    Returns:
        成功した場合True
    """
    try:
        output_wav = OUTPUT_DIR / f"{audio_id}.wav"
        
        if not text:
            print(f"  ⚠ {audio_id}: テキストが空のためスキップ", flush=True)
            return False
        
        # 開始ログ
        print(f"\n[開始] {audio_id}.wav の生成を開始します", flush=True)
        print(f"  テキスト: {text}", flush=True)
        print(f"  モデル: {GEMINI_MODEL}", flush=True)
        print(f"  ボイス: {VOICE_NAME}", flush=True)
        print(f"  Pitch: 2.0, Speed: 1.05", flush=True)
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz", flush=True)
        
        # Gemini APIで音声合成
        audio_data = synthesize_with_gemini(text, api_key)
        
        if not audio_data:
            print(f"  ✗ {audio_id}: 音声合成に失敗しました", flush=True)
            return False
        
        # WAV形式に変換（必要に応じて）
        wav_data = convert_to_wav(audio_data, SAMPLE_RATE)
        
        # WAVファイルとして保存
        with open(output_wav, "wb") as f:
            f.write(wav_data)
        
        file_size = output_wav.stat().st_size
        # 完了ログ（サイズ含む）
        print(f"[完了] {audio_id}.wav の生成が完了しました", flush=True)
        print(f"  ファイルパス: {output_wav}", flush=True)
        print(f"  ファイルサイズ: {file_size:,} bytes ({file_size / 1024:.2f} KB)", flush=True)
        
        # レート制限対策: 指定秒数スリープ
        if sleep_seconds > 0:
            import time
            print(f"  レート制限回避のため {sleep_seconds}秒待機中...", flush=True)
            time.sleep(sleep_seconds)
        
        return True
        
    except Exception as e:
        print(f"  ✗ {audio_id}: エラー - {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("Gemini 2.0/2.5 API 日本語TTS音声生成")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # APIキーを取得
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("エラー: APIキーが見つかりません。")
        return 1
    
    print(f"\n✓ APIキー認証を使用")
    
    if not GENAI_AVAILABLE:
        print("エラー: google-genai がインストールされていません。")
        print("インストール: pip install google-genai")
        return 1
    
    # 音声リスト読み込み（既存ファイルをスキップ）
    print(f"\n音声リスト読み込み中...")
    voice_texts = load_voice_list(skip_existing=True)
    
    if not voice_texts:
        print("✓ すべての音声ファイルが既に生成済みです。")
        return 0
    
    print(f"✓ {len(voice_texts)}件の未生成音声テキストを読み込みました")
    
    # TTS設定表示
    print(f"\nTTS設定:")
    print(f"  モデル: {GEMINI_MODEL}")
    print(f"  ボイス: {VOICE_NAME}")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  ビット深度: {BIT_DEPTH}bit")
    print(f"  チャンネル: {CHANNELS} (モノラル)")
    print(f"  出力形式: WAV")
    print(f"  出力ディレクトリ: {OUTPUT_DIR}")
    
    # 音声ファイル生成（全自動生成モード）
    print(f"\n音声ファイル生成中（全自動生成モード）...", flush=True)
    print(f"  レート制限対策: 1件ごとに7秒スリープ", flush=True)
    print(f"  エラー継続: 500エラーなどが出ても止まらず続行します", flush=True)
    print(f"", flush=True)
    
    success_count = 0
    failed_list = []
    
    for audio_id in sorted(voice_texts.keys()):
        text = voice_texts[audio_id]
        try:
            if generate_audio_file(audio_id, text, api_key, sleep_seconds=7.0):
                success_count += 1
            else:
                failed_list.append(audio_id)
                print(f"  ⚠ {audio_id}: 生成失敗（エラーログを確認してください）", flush=True)
        except Exception as e:
            failed_list.append(audio_id)
            print(f"  ✗ {audio_id}: 予期しないエラー - {e}", flush=True)
            import traceback
            traceback.print_exc()
        
        # 各ファイル生成後に強制的にflush
        sys.stdout.flush()
    
    # 結果表示
    print(f"\n" + "=" * 60)
    print(f"音声ファイル生成完了")
    print(f"  成功: {success_count}件")
    print(f"  失敗: {len(failed_list)}件")
    print(f"  合計: {len(voice_texts)}件")
    print("=" * 60)
    
    if failed_list:
        print(f"\n⚠ 生成に失敗した番号のリスト:")
        for failed_id in failed_list:
            print(f"  - {failed_id}")
        print(f"\n合計 {len(failed_list)}件の生成に失敗しました。")
        return 1
    else:
        print("\n✓ すべての音声ファイルが正常に生成されました！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
