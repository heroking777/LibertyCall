#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音声ファイルをASRでテキスト化するテストスクリプト

使い方:
    python3 scripts/test_audio_asr.py <audio_file.wav>
"""

import sys
import wave
import numpy as np
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    WhisperModel = None

def transcribe_wav_file(audio_file_path: str) -> str:
    """
    WAVファイルをテキストに変換（Whisper使用）
    
    :param audio_file_path: WAVファイルのパス
    :return: 認識されたテキスト
    """
    if not FASTER_WHISPER_AVAILABLE:
        print("❌ エラー: faster-whisper がインストールされていません。")
        print("   pip install faster-whisper を実行してください。")
        sys.exit(1)
    
    # WAVファイルを読み込む
    try:
        with wave.open(audio_file_path, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except Exception as e:
        print(f"❌ エラー: WAVファイルの読み込みに失敗しました: {e}")
        sys.exit(1)
    
    # PCM16 (16bit) に変換
    if sample_width == 1:
        # 8bit -> 16bit
        audio_data = np.frombuffer(frames, dtype=np.uint8).astype(np.int16)
        audio_data = (audio_data - 128) * 256
    elif sample_width == 2:
        # 16bit
        audio_data = np.frombuffer(frames, dtype=np.int16)
    elif sample_width == 4:
        # 32bit -> 16bit
        audio_data = np.frombuffer(frames, dtype=np.int32).astype(np.int16)
    else:
        print(f"❌ エラー: サポートされていないサンプル幅: {sample_width * 8}bit")
        sys.exit(1)
    
    # モノラルに変換（ステレオの場合）
    if n_channels == 2:
        audio_data = audio_data.reshape(-1, 2)
        audio_data = audio_data.mean(axis=1).astype(np.int16)
    
    # 16kHzにリサンプリング（必要に応じて）
    if sample_rate != 16000:
        # 簡易リサンプリング（線形補間）
        try:
            from scipy import signal
            num_samples = int(len(audio_data) * 16000 / sample_rate)
            audio_data = signal.resample(audio_data, num_samples).astype(np.int16)
            sample_rate = 16000
        except ImportError:
            # scipyがインストールされていない場合は、単純にスキップ
            # Whisperは様々なサンプリングレートに対応しているため、そのまま処理
            print(f"⚠️  警告: scipyがインストールされていません。サンプリングレート変換をスキップします。", file=sys.stderr)
            print(f"   現在のサンプリングレート: {sample_rate}Hz（Whisperは自動的に処理します）", file=sys.stderr)
    
    # float32に正規化（-1.0 ～ 1.0）
    audio_array = audio_data.astype(np.float32) / 32768.0
    
    # Whisperで認識
    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            audio_array,
            language="ja",
            temperature=0.0,
            beam_size=5,
            vad_filter=False,
        )
        
        # 認識結果を結合
        text = "".join([segment.text for segment in segments]).strip()
        return text
    except Exception as e:
        print(f"❌ エラー: ASR認識に失敗しました: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/test_audio_asr.py <audio_file.wav>")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    
    if not Path(audio_file).exists():
        print(f"❌ エラー: ファイルが見つかりません: {audio_file}")
        sys.exit(1)
    
    print(f"🎧 音声ファイルを認識中: {audio_file}")
    text = transcribe_wav_file(audio_file)
    
    if text:
        print(f"🗣️  認識結果: {text}")
        
        # 認識結果をファイルに保存（ASR評価用）
        results_dir = PROJECT_ROOT / "tts_test" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名から拡張子を除いた名前で保存
        audio_name = Path(audio_file).stem
        result_file = results_dir / f"{audio_name}.txt"
        
        try:
            with open(result_file, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            print(f"⚠️  警告: 認識結果の保存に失敗しました: {e}", file=sys.stderr)
        
        # 標準出力に出力（他のスクリプトから呼び出す場合）
        print(text, end="")
    else:
        print("⚠️  認識結果が空です。")
        sys.exit(1)

if __name__ == "__main__":
    main()

