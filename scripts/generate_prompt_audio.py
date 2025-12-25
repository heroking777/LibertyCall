#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
催促音声（フォーマル版）生成スクリプト

クライアント000用の催促音声を生成します。
"""

import os
import sys
from pathlib import Path

# メインスクリプトの関数をインポート
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.generate_gemini_tts import (
    synthesize_with_gemini,
    convert_to_wav,
    OUTPUT_DIR,
    SAMPLE_RATE,
    SYSTEM_PROMPT,
    check_credentials,
    ensure_directories
)

# 催促音声のテキスト
PROMPT_TEXTS = {
    "prompt_001_8k": "もしもし、お声が少し遠いようでございますが、いかがでしょうか",
    "prompt_002_8k": "もしもし、こちらの音声はお聞き取りいただけておりますでしょうか",
    "prompt_003_8k": "大変申し訳ございません。お声の確認ができませんでしたため、この通話を終了させていただきます。ご用件がございましたら、電波状況をご確認の上、改めてお電話いただけますと幸いです。失礼いたします"
}


def generate_prompt_audio(prompt_id: str, text: str, api_key: str) -> bool:
    """催促音声ファイルを生成"""
    try:
        output_wav = OUTPUT_DIR / f"{prompt_id}.wav"
        
        print(f"\n[開始] {prompt_id}.wav の生成を開始します", flush=True)
        print(f"  テキスト: {text}", flush=True)
        
        # Gemini APIで音声合成
        audio_data = synthesize_with_gemini(text, api_key)
        
        if not audio_data:
            print(f"  ✗ {prompt_id}: 音声合成に失敗しました", flush=True)
            return False
        
        # WAV形式に変換
        wav_data = convert_to_wav(audio_data, SAMPLE_RATE)
        
        # WAVファイルとして保存
        with open(output_wav, "wb") as f:
            f.write(wav_data)
        
        file_size = output_wav.stat().st_size
        print(f"[完了] {prompt_id}.wav の生成が完了しました", flush=True)
        print(f"  ファイルパス: {output_wav}", flush=True)
        print(f"  ファイルサイズ: {file_size:,} bytes ({file_size / 1024:.2f} KB)", flush=True)
        return True
        
    except Exception as e:
        print(f"  ✗ {prompt_id}: エラー - {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("催促音声（フォーマル版）生成")
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
    
    # 催促音声生成
    print(f"\n催促音声ファイル生成中...")
    success_count = 0
    failed_list = []
    
    for prompt_id, text in PROMPT_TEXTS.items():
        if generate_prompt_audio(prompt_id, text, api_key):
            success_count += 1
        else:
            failed_list.append(prompt_id)
        sys.stdout.flush()
    
    # 結果表示
    print(f"\n" + "=" * 60)
    print(f"催促音声ファイル生成完了")
    print(f"  成功: {success_count}件")
    print(f"  失敗: {len(failed_list)}件")
    print(f"  合計: {len(PROMPT_TEXTS)}件")
    print("=" * 60)
    
    if failed_list:
        print(f"\n⚠ 生成に失敗したファイル:")
        for failed_id in failed_list:
            print(f"  - {failed_id}")
        return 1
    else:
        print("\n✓ すべての催促音声ファイルが正常に生成されました！")
        return 0


if __name__ == "__main__":
    sys.exit(main())

