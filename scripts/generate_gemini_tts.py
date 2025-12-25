#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.0/2.5 APIを使用した日本語TTS（音声合成）スクリプト
一撃必殺モード：リトライなし、失敗したら即スキップ
"""

import os
import sys
import wave
import io
import base64
from pathlib import Path
from typing import Optional, Tuple

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
GEMINI_MODEL = "gemini-2.5-flash-preview-tts"

# 音声名（日本語対応）
VOICE_NAME = "Kore"  # 固定: 一貫した声質を保つため（確定レシピ）


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
        return False
    return True


def ensure_directories():
    """必要なディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ確認: {OUTPUT_DIR}")


def load_voice_list(skip_existing: bool = False) -> dict:
    """voice_list_000.tsvから音声テキストを読み込む"""
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


def synthesize_with_gemini(text: str, client) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Gemini APIを使用してテキストから音声を合成する（1回のみ、リトライなし）
    
    Args:
        text: 音声化するテキスト（TSVのテキストをそのまま使用）
        client: 再利用するgenai.Clientインスタンス
    
    Returns:
        (音声データ（bytes）または None, エラー理由（str）または None)
    """
    try:
        if not GENAI_AVAILABLE:
            return None, "GENAI_NOT_AVAILABLE"
        
        # TSVのテキストをそのまま送る（システムプロンプトなし、余計な指示なし）
        
        # セーフティ設定を全開放（TTS APIでサポートされているテキスト用カテゴリのみ）
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
        
        # 生成リクエスト（シンプルに、余計な指示なし）
        # PitchやRateの指示はテキストに混ぜず、speechConfigで制御（できない場合はデフォルト）
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
        
        # TSVのテキストだけをcontentsに渡す（システムプロンプトなし）
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=text,  # システムプロンプトなし、テキストだけ
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
        
        return None, error_reason


def convert_to_wav(audio_data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """音声データをWAV形式に変換する"""
    if audio_data[:4] == b'RIFF':
        return audio_data
    
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BIT_DEPTH // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)
    
    return wav_buffer.getvalue()


def generate_audio_file(audio_id: str, text: str, client) -> Tuple[bool, Optional[str]]:
    """Gemini APIを使用して音声ファイルを生成（1回のみ、リトライなし）"""
    try:
        output_wav = OUTPUT_DIR / f"{audio_id}.wav"
        
        if not text:
            return False, "EMPTY_TEXT"
        
        # 開始ログ
        print(f"\n[開始] {audio_id}.wav の生成を開始します", flush=True)
        print(f"  テキスト: {text}", flush=True)
        
        # Gemini APIで音声合成（1回のみ、リトライなし、再利用クライアント使用）
        audio_data, error_reason = synthesize_with_gemini(text, client)
        
        if not audio_data:
            print(f"  ✗ {audio_id}: 音声合成に失敗しました (理由: {error_reason})", flush=True)
            return False, error_reason
        
        # WAV形式に変換
        wav_data = convert_to_wav(audio_data, SAMPLE_RATE)
        
        # WAVファイルとして保存
        with open(output_wav, "wb") as f:
            f.write(wav_data)
        
        file_size = output_wav.stat().st_size
        print(f"[完了] {audio_id}.wav の生成が完了しました", flush=True)
        print(f"  ファイルパス: {output_wav}", flush=True)
        print(f"  ファイルサイズ: {file_size:,} bytes ({file_size / 1024:.2f} KB)", flush=True)
        
        return True, None
        
    except Exception as e:
        error_reason = f"EXCEPTION_{type(e).__name__}"
        print(f"  ✗ {audio_id}: エラー - {e}", flush=True)
        return False, error_reason


def main():
    """メイン処理"""
    print("=" * 60)
    print("Gemini 2.0/2.5 API 日本語TTS音声生成（一撃必殺モード）")
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
    
    # 音声リスト読み込み（006以降の未生成分をすべて処理）
    print(f"\n音声リスト読み込み中...")
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
    
    # 音声ファイル生成（完全放置・突破仕様：APIが拒絶できない形）
    print(f"\n音声ファイル生成中（完全放置・突破仕様）...", flush=True)
    print(f"  リトライ: 無効（1回のみ実行、失敗したら即スキップ）", flush=True)
    print(f"  ランダム待機: 15秒〜25秒のランダム待機（Bot判定回避）", flush=True)
    print(f"  429エラー時: 即座にシステム停止（無駄なAPI呼び出しを防止）", flush=True)
    print(f"  クライアント: 1つのクライアントを使い回し（リコネクト削減）", flush=True)
    print(f"  システムプロンプト: 完全削除（TSVテキストのみ）", flush=True)
    print(f"  パラメータ: Model={GEMINI_MODEL}, Voice={VOICE_NAME}, Temperature=0.0", flush=True)
    print(f"", flush=True)
    
    # 1つのクライアントを作成して使い回す（リコネクトのオーバーヘッドを削る）
    client = genai.Client(api_key=api_key)
    print(f"✓ クライアント初期化完了（再利用モード）", flush=True)
    
    success_count = 0
    failed_list = {}  # {audio_id: error_reason}
    total_count = len(voice_texts)
    import time
    import random
    
    for idx, audio_id in enumerate(sorted(voice_texts.keys()), 1):
        text = voice_texts[audio_id]
        print(f"\n[{idx}/{total_count}] {audio_id} を処理中...", flush=True)
        
        try:
            # 一撃必殺モード：1回のみ実行（再利用クライアント使用）
            success, error_reason = generate_audio_file(audio_id, text, client)
            
            if success:
                success_count += 1
                print(f"  ✓ {audio_id}: 生成成功（進捗: {success_count}/{total_count}）", flush=True)
            else:
                failed_list[audio_id] = error_reason
                print(f"  ✗ {audio_id}: 生成失敗 (理由: {error_reason})", flush=True)
                
                # 429エラー（API制限）が検出されたら即座にシステムを停止
                if error_reason == "429_QUOTA_EXCEEDED":
                    print(f"\n" + "=" * 60, flush=True)
                    print(f"⚠ API制限エラー（429 RESOURCE_EXHAUSTED）が検出されました", flush=True)
                    print(f"  1日の上限（100回）を超えた可能性があります", flush=True)
                    print(f"  無駄なAPI呼び出し（入力トークン課金）を防ぐため、システムを即座に停止します", flush=True)
                    print(f"  成功: {success_count}件 / 処理済み: {idx}件 / 残り: {total_count - idx}件", flush=True)
                    print("=" * 60, flush=True)
                    sys.exit(1)
                
        except KeyboardInterrupt:
            print(f"\n\n⚠ ユーザーによる中断が検出されました。", flush=True)
            print(f"  成功: {success_count}件 / 残り: {total_count - success_count}件", flush=True)
            return 1
        except Exception as e:
            failed_list[audio_id] = f"EXCEPTION_{type(e).__name__}"
            print(f"  ✗ {audio_id}: 予期しないエラー - {e}", flush=True)
        
        # 成功・失敗に関わらず、15秒〜25秒のランダム待機（Bot判定回避）
        wait_seconds = random.uniform(15, 25)
        print(f"  {wait_seconds:.1f}秒待機中（ランダム）...", flush=True)
        time.sleep(wait_seconds)
        
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

