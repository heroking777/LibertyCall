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
VOICE_NAME = "Kore"  # 固定: 一貫した声質を保つため（確定レシピ）

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

# 短いセリフ用の簡略化プロンプト
SHORT_TEXT_PROMPT = """[設定: Pitch:+2.0, Rate:1.05]"""


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


def synthesize_with_gemini(text: str, api_key: str) -> tuple[Optional[bytes], Optional[str]]:
    """
    Gemini APIを使用してテキストから音声を合成する（google-genaiパッケージ使用）
    リトライなし、1回のみ実行
    
    Args:
        text: 音声化するテキスト
        api_key: APIキー
    
    Returns:
        (音声データ（bytes）または None, エラー理由（str）または None)
    """
    try:
        if not GENAI_AVAILABLE:
            print("エラー: google-genai がインストールされていません。", flush=True)
            return None, "GENAI_NOT_AVAILABLE"
        
        # クライアントの初期化
        client = genai.Client(api_key=api_key)
            
            # システムプロンプトを固定して一貫した声質を保つ
            # 短いセリフ（5文字以下）の場合は特別処理
            is_short_text = len(text.strip()) <= 5
            
            if is_short_text:
                # 短いセリフの場合：
                # 1. テキストを少し長くして波形生成を安定させる
                # 「はい。」→「はい、承知いたしました。」のように自然に拡張
                if text.strip() == "はい。":
                    enhanced_text = "はい、承知いたしました。"
                elif text.strip() == "いいえ。":
                    enhanced_text = "いいえ、そのようではございません。"
                else:
                    # その他の短いセリフは語尾に「。。。」を追加
                    enhanced_text = f"{text.strip()}。。。"
                # 2. 通常のプロンプトを使用（簡略化プロンプトは使わない）
                prompt = f"{SYSTEM_PROMPT} {enhanced_text}"
            else:
                # 通常のセリフはそのまま
                prompt = f"{SYSTEM_PROMPT} {text}"
            
            # セーフティ設定を全開放（TTS APIでサポートされているテキスト用カテゴリのみ）
            # IMAGE関連とJAILBREAK、CIVIC_INTEGRITYはTTS APIではサポートされていないため除外
            safety_settings = [
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE
                ),
            ]
            
            # 生成リクエスト
            # Gemini 2.0 Flash は 'AUDIO' モダリティを指定する必要があります
            # 注意: SpeechConfigにはpitch/speaking_rateパラメータがサポートされていないため、
            # プロンプト内で数値として明示的に指示しています（Pitch: +2.0, Rate: 1.05）
            config = types.GenerateContentConfig(
                responseModalities=["AUDIO"],
                temperature=0.0,
                safetySettings=safety_settings,
                speechConfig=types.SpeechConfig(
                    voiceConfig=types.VoiceConfig(
                        prebuiltVoiceConfig=types.PrebuiltVoiceConfig(
                            voiceName=VOICE_NAME
                        )
                    )
                )
            )
            
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config
        )
            
        # 音声データの取り出し（パス固定版）
        # response.candidates[0].content.parts[0].inline_data.data から直接バイナリを取得
        audio_data = None
        
        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]
            
            if hasattr(candidate, 'content') and candidate.content is not None:
                if hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                    # パス固定: parts[0].inline_data.data
                    part = candidate.content.parts[0]
                    
                    if hasattr(part, 'inline_data') and part.inline_data is not None:
                        if hasattr(part.inline_data, 'data'):
                            audio_data = part.inline_data.data
                            
                            if audio_data and len(audio_data) > 0:
                                if isinstance(audio_data, str):
                                    return base64.b64decode(audio_data), None
                                return audio_data, None
        
        # 音声データが空の場合は失敗として返す
        finish_reason = None
        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, 'finish_reason', None)
        error_reason = "EMPTY_DATA"
        if finish_reason:
            error_reason = f"{finish_reason}"
        print(f"  警告: 音声データが見つかりませんでした (finish_reason: {finish_reason})", flush=True)
        return None, error_reason
                    
    except Exception as e:
        error_str = str(e)
        error_reason = "UNKNOWN_ERROR"
        
        # エラー理由を特定
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            error_reason = "429_QUOTA_EXCEEDED"
        elif "500" in error_str or "INTERNAL" in error_str:
            error_reason = "500_INTERNAL_ERROR"
        elif "400" in error_str or "INVALID_ARGUMENT" in error_str:
            error_reason = "400_INVALID_ARGUMENT"
        else:
            error_reason = f"ERROR_{type(e).__name__}"
        
        print(f"  エラー: Gemini API音声合成に失敗しました: {error_reason}", flush=True)
        return None, error_reason


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


def generate_audio_file(audio_id: str, text: str, api_key: str, sleep_seconds: float = 0.0) -> tuple[bool, Optional[str]]:
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
        
        # デバッグ: 003のテキストを強制的に書き換え
        if audio_id == "003":
            original_text = text
            text = "今日はとても天気がいいので、散歩に行きたいですね。"
            print(f"  デバッグ: 003のテキストを強制的に書き換えました", flush=True)
            print(f"  元のテキスト: {original_text}", flush=True)
            print(f"  新しいテキスト: {text}", flush=True)
        
        # 開始ログ
        print(f"\n[開始] {audio_id}.wav の生成を開始します", flush=True)
        print(f"  テキスト: {text}", flush=True)
        print(f"  モデル: {GEMINI_MODEL}", flush=True)
        print(f"  ボイス: {VOICE_NAME}", flush=True)
        print(f"  Pitch: 2.0, Speed: 1.05", flush=True)
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz", flush=True)
        
        # Gemini APIで音声合成（無限リトライ無効、1回のみ）
        audio_data = synthesize_with_gemini(text, api_key, infinite_retry=False, max_attempts=1)
        
        if not audio_data:
            if infinite_retry:
                # 無限リトライモードでは、ここに到達することはないはず
                print(f"  ⚠ {audio_id}: 予期しないエラー（無限リトライ継続中）", flush=True)
                return False
            else:
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
        
        return True, None
        
    except Exception as e:
        error_reason = f"EXCEPTION_{type(e).__name__}"
        print(f"  ✗ {audio_id}: エラー - {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False, error_reason


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
    # テストモード: 003と005のみを処理
    TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
    
    print(f"\n音声リスト読み込み中...")
    if TEST_MODE:
        print(f"  テストモード: 003と005のみを処理します", flush=True)
        voice_texts = {}
        all_texts = load_voice_list(skip_existing=False)
        for test_id in ["003", "005"]:
            if test_id in all_texts:
                voice_texts[test_id] = all_texts[test_id]
    else:
        # 006以降の未生成分をすべて処理
        all_texts = load_voice_list(skip_existing=True)
        voice_texts = {}
        for audio_id, text in all_texts.items():
            # 006以降のみ処理（000-005は除外）
            try:
                audio_id_int = int(audio_id)
                if audio_id_int >= 6:
                    voice_texts[audio_id] = text
            except ValueError:
                # 数値でないID（例: 006_SYS）も処理
                if not audio_id.startswith(("000", "001", "002", "003", "004", "005")):
                    voice_texts[audio_id] = text
    
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
    
    # 音声ファイル生成（一撃必殺モード：リトライなし）
    print(f"\n音声ファイル生成中（一撃必殺モード：リトライなし）...", flush=True)
    print(f"  レート制限対策: 1件ごとに10秒スリープ（APIに優しい設定）", flush=True)
    print(f"  リトライ: 無効（1回のみ実行、失敗したら即スキップ）", flush=True)
    print(f"  429エラー対策: 429エラーの場合のみ3分待機してから次へ", flush=True)
    print(f"  パラメータ: Model={GEMINI_MODEL}, Voice={VOICE_NAME}, Pitch=+2.0, Rate=1.05, Temperature=0.0", flush=True)
    print(f"", flush=True)
    
    success_count = 0
    failed_list = {}  # {audio_id: error_reason}
    total_count = len(voice_texts)
    import time
    
    for idx, audio_id in enumerate(sorted(voice_texts.keys()), 1):
        text = voice_texts[audio_id]
        print(f"\n[{idx}/{total_count}] {audio_id} を処理中...", flush=True)
        
        try:
            # 一撃必殺モード：1回のみ実行
            success, error_reason = generate_audio_file(audio_id, text, api_key, sleep_seconds=10.0)
            
            if success:
                success_count += 1
                print(f"  ✓ {audio_id}: 生成成功（進捗: {success_count}/{total_count}）", flush=True)
            else:
                failed_list[audio_id] = error_reason
                print(f"  ✗ {audio_id}: 生成失敗 (理由: {error_reason})", flush=True)
                
                # 429エラーの場合のみ3分待機
                if error_reason == "429_QUOTA_EXCEEDED":
                    print(f"  ⚠ 429エラー検出: クォータ回復を待つため3分間停止します...", flush=True)
                    time.sleep(180)  # 3分 = 180秒
                    print(f"  待機完了、次の番号へ進みます", flush=True)
                
        except KeyboardInterrupt:
            print(f"\n\n⚠ ユーザーによる中断が検出されました。", flush=True)
            print(f"  成功: {success_count}件 / 残り: {total_count - success_count}件", flush=True)
            return 1
        except Exception as e:
            failed_list[audio_id] = f"EXCEPTION_{type(e).__name__}"
            print(f"  ✗ {audio_id}: 予期しないエラー - {e}", flush=True)
        
        # 各ファイル生成後に強制的にflush
        sys.stdout.flush()
    
    # 結果表示
    print(f"\n" + "=" * 60)
    print(f"音声ファイル生成完了")
    print(f"  成功: {success_count}件")
    print(f"  失敗: {len(failed_list)}件")
    print(f"  合計: {total_count}件")
    print("=" * 60)
    
    if failed_list:
        print(f"\n⚠ 生成に失敗した番号のリスト:")
        for failed_id, error_reason in sorted(failed_list.items()):
            print(f"  - {failed_id}: 失敗 ({error_reason})")
    
    if success_count == total_count:
        print("\n✓ すべての音声ファイルが正常に生成されました！")
        return 0
    else:
        print(f"\n⚠ 一部の音声ファイルの生成に失敗しました（成功: {success_count}/{total_count}）")
        return 1


if __name__ == "__main__":
    sys.exit(main())
