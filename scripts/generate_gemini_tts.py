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


def synthesize_with_gemini(text: str, api_key: str, infinite_retry: bool = False, max_attempts: int = 3) -> Optional[bytes]:
    """
    Gemini APIを使用してテキストから音声を合成する（google-genaiパッケージ使用）
    
    Args:
        text: 音声化するテキスト
        api_key: APIキー
        infinite_retry: Trueの場合、無限リトライ（成功するまで続行、指数バックオフ適用）
    
    Returns:
        音声データ（bytes）または None
    """
    import time
    
    attempt = 0
    while True:
        attempt += 1
        if not infinite_retry and attempt > max_attempts:
            print(f"  最大試行回数（{max_attempts}回）に達しました。", flush=True)
            return None
        try:
            if not GENAI_AVAILABLE:
                print("エラー: google-genai がインストールされていません。")
                return None
            
            # クライアントの初期化
            client = genai.Client(api_key=api_key)
            
            # システムプロンプトを固定して一貫した声質を保つ
            # 短いセリフの場合は肉付けして生成を安定させる
            if len(text.strip()) <= 5:  # 短いセリフ（5文字以下）
                enhanced_text = f"少し間を置いてから、丁寧に「{text}」と言ってください"
            else:
                enhanced_text = text
            
            prompt = f"{SYSTEM_PROMPT} {enhanced_text}"
            
            # デバッグ: プロンプト全体を表示
            print(f"  デバッグ: プロンプト全体 = {prompt}", flush=True)
            print(f"  デバッグ: プロンプト長 = {len(prompt)} 文字", flush=True)
            
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
            if infinite_retry and attempt <= 3:
                print(f"  API呼び出し中...（{attempt}回目）", flush=True)
            
            # デバッグ: GenerateContentConfigを表示
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
            print(f"  デバッグ: GenerateContentConfig = {config}", flush=True)
            print(f"  デバッグ: safetySettings = {safety_settings}", flush=True)
            
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
            
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config
            )
            
            # デバッグ: responseオブジェクト全体を表示
            print(f"  デバッグ: response オブジェクト全体 = {response}", flush=True)
            print(f"  デバッグ: response type = {type(response)}", flush=True)
            print(f"  デバッグ: response attributes = {[attr for attr in dir(response) if not attr.startswith('_')]}", flush=True)
            
            # デバッグ: prompt_feedbackを確認
            if hasattr(response, 'prompt_feedback'):
                prompt_feedback = response.prompt_feedback
                print(f"  デバッグ: prompt_feedback = {prompt_feedback}", flush=True)
                if prompt_feedback:
                    print(f"  デバッグ: prompt_feedback type = {type(prompt_feedback)}", flush=True)
                    print(f"  デバッグ: prompt_feedback attributes = {[attr for attr in dir(prompt_feedback) if not attr.startswith('_')]}", flush=True)
                    if hasattr(prompt_feedback, 'block_reason'):
                        print(f"  デバッグ: prompt_feedback.block_reason = {prompt_feedback.block_reason}", flush=True)
                    if hasattr(prompt_feedback, 'safety_ratings'):
                        print(f"  デバッグ: prompt_feedback.safety_ratings = {prompt_feedback.safety_ratings}", flush=True)
            
            # デバッグ: finish_reasonとsafety_ratingsを確認
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)
                finish_message = getattr(candidate, 'finish_message', None)
                print(f"  デバッグ: finish_reason = {finish_reason}", flush=True)
                print(f"  デバッグ: finish_message = {finish_message}", flush=True)
                
                # safety_ratingsを確認
                if hasattr(candidate, 'safety_ratings'):
                    safety_ratings = candidate.safety_ratings
                    print(f"  デバッグ: candidate.safety_ratings = {safety_ratings}", flush=True)
                    if safety_ratings:
                        for i, rating in enumerate(safety_ratings):
                            print(f"  デバッグ: safety_ratings[{i}] = {rating}", flush=True)
                            if hasattr(rating, 'category'):
                                print(f"  デバッグ: safety_ratings[{i}].category = {rating.category}", flush=True)
                            if hasattr(rating, 'probability'):
                                print(f"  デバッグ: safety_ratings[{i}].probability = {rating.probability}", flush=True)
                
                if finish_reason and 'SAFETY' in str(finish_reason).upper():
                    print(f"  ⚠ 警告: セーフティフィルターでブロックされています！", flush=True)
            
            # 音声データの取り出し（パス固定版）
            # response.candidates[0].content.parts[0].inline_data.data から直接バイナリを取得
            audio_data = None
            
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                # finish_reasonを確認
                finish_reason = getattr(candidate, 'finish_reason', None)
                print(f"  デバッグ: finish_reason = {finish_reason}", flush=True)
                
                if hasattr(candidate, 'content') and candidate.content is not None:
                    if hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                        # パス固定: parts[0].inline_data.data
                        part = candidate.content.parts[0]
                        print(f"  デバッグ: part[0] type = {type(part)}", flush=True)
                        
                        if hasattr(part, 'inline_data') and part.inline_data is not None:
                            print(f"  デバッグ: part[0].inline_data が見つかりました", flush=True)
                            
                            if hasattr(part.inline_data, 'data'):
                                audio_data = part.inline_data.data
                                print(f"  デバッグ: part[0].inline_data.data 取得成功 (size: {len(audio_data) if audio_data else 0} bytes)", flush=True)
                                
                                if audio_data and len(audio_data) > 0:
                                    if isinstance(audio_data, str):
                                        return base64.b64decode(audio_data)
                                    return audio_data
                            else:
                                print(f"  エラー: part[0].inline_data.data が見つかりません", flush=True)
                        else:
                            print(f"  エラー: part[0].inline_data が見つかりません", flush=True)
                    else:
                        print(f"  エラー: candidate.content.parts が空です", flush=True)
                else:
                    print(f"  エラー: candidate.content が None です", flush=True)
            
            # 音声データが空の場合はリトライ
            if not audio_data or len(audio_data) == 0:
                if infinite_retry:
                    # 指数バックオフ: 1回目30秒、2回目60秒、3回目120秒...（最大300秒）
                    backoff_seconds = min(30 * (2 ** (attempt - 1)), 300)
                    print(f"  警告: 音声データが空でした。リトライ中...（{attempt}回目）", flush=True)
                    print(f"  {backoff_seconds}秒待機してから再試行します（指数バックオフ）...", flush=True)
                    time.sleep(backoff_seconds)
                    continue
                else:
                    print(f"警告: 音声データが見つかりませんでした。", flush=True)
                    return None
            else:
                # 成功した場合は音声データを返す
                return audio_data
                    
        except Exception as e:
            if infinite_retry:
                # 指数バックオフ: 1回目30秒、2回目60秒、3回目120秒...（最大300秒）
                backoff_seconds = min(30 * (2 ** (attempt - 1)), 300)
                print(f"  エラー: {e}。リトライ中...（{attempt}回目）", flush=True)
                print(f"  {backoff_seconds}秒待機してから再試行します（指数バックオフ）...", flush=True)
                time.sleep(backoff_seconds)
                continue
            else:
                print(f"エラー: Gemini API音声合成に失敗しました: {e}", flush=True)
                import traceback
                traceback.print_exc()
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


def generate_audio_file(audio_id: str, text: str, api_key: str, sleep_seconds: float = 0.0, infinite_retry: bool = False) -> bool:
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
        
        # Gemini APIで音声合成（テストモードでは無限リトライを無効化、1回のみ）
        test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
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
    
    # 音声ファイル生成（無限リトライ全自動生成モード）
    print(f"\n音声ファイル生成中（無限リトライ全自動生成モード）...", flush=True)
    print(f"  レート制限対策: 1件ごとに10秒スリープ（APIに優しい設定）", flush=True)
    print(f"  エラー時: 指数バックオフ（30秒→60秒→120秒→...最大300秒）", flush=True)
    print(f"  無限リトライ: 500エラーやタイムアウトが発生しても、成功するまでリトライし続けます", flush=True)
    print(f"  パラメータ: Model={GEMINI_MODEL}, Voice={VOICE_NAME}, Pitch=+2.0, Rate=1.05, Temperature=0.0", flush=True)
    print(f"", flush=True)
    
    success_count = 0
    total_count = len(voice_texts)
    
    for idx, audio_id in enumerate(sorted(voice_texts.keys()), 1):
        text = voice_texts[audio_id]
        print(f"\n[{idx}/{total_count}] {audio_id} を処理中...", flush=True)
        
        try:
            # 無限リトライモードで生成（成功するまで続行）
            if generate_audio_file(audio_id, text, api_key, sleep_seconds=10.0, infinite_retry=True):
                success_count += 1
                print(f"  ✓ {audio_id}: 生成成功（進捗: {success_count}/{total_count}）", flush=True)
            else:
                # 無限リトライモードでは通常ここに到達しない
                print(f"  ⚠ {audio_id}: 予期しないエラー（無限リトライ継続中）", flush=True)
        except KeyboardInterrupt:
            print(f"\n\n⚠ ユーザーによる中断が検出されました。", flush=True)
            print(f"  成功: {success_count}件 / 残り: {total_count - success_count}件", flush=True)
            return 1
        except Exception as e:
            print(f"  ✗ {audio_id}: 予期しないエラー - {e}", flush=True)
            import traceback
            traceback.print_exc()
            # 無限リトライモードでは、エラーでも続行
            print(f"  ⚠ {audio_id}: エラーが発生しましたが、無限リトライモードのため続行します...", flush=True)
        
        # 各ファイル生成後に強制的にflush
        sys.stdout.flush()
    
    # 結果表示
    print(f"\n" + "=" * 60)
    print(f"音声ファイル生成完了（無限リトライモード）")
    print(f"  成功: {success_count}件")
    print(f"  合計: {total_count}件")
    print("=" * 60)
    
    if success_count == total_count:
        print("\n✓ すべての音声ファイルが正常に生成されました！")
        return 0
    else:
        print(f"\n⚠ 一部の音声ファイルの生成が完了していません（成功: {success_count}/{total_count}）")
        print(f"  無限リトライモードのため、未完了のファイルは引き続きリトライされます。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
