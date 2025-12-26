#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F5-TTSを使用した日本語TTS（音声合成）スクリプト
Google AI Studioから出力した高品質なリファレンス音声を使用して一括生成

【使用方法】
1. 仮想環境をアクティベート
2. scripts/ref.wav を準備（参照音声ファイル）
3. scripts/data.txt を準備（1行1セリフ）
4. スクリプトを実行: python scripts/generate_f5_tts_clone.py
"""

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent
REF_AUDIO_FILE = SCRIPTS_DIR / "ref.wav"
DATA_FILE = SCRIPTS_DIR / "data.txt"
OUTPUT_DIR = SCRIPTS_DIR / "output"

# 参照テキスト（ref.wavに対応するテキスト）
REF_TEXT = "はい、かしこまりました。担当の者にお繋ぎいたしますので、少々お待ちくださいませ。お電話が大変込み合っておりますが、順番にご案内いたします。"

# グローバル変数: モデルとボコーダーを一度だけロード
_model_obj = None
_vocoder = None


def check_f5_tts_available() -> bool:
    """F5-TTSが利用可能か確認"""
    try:
        import f5_tts
        return True
    except ImportError:
        print("✗ エラー: f5_tts がインストールされていません")
        print("  インストール: pip install f5-tts")
        return False


def check_ref_audio() -> bool:
    """参照音声ファイルの存在確認"""
    if not REF_AUDIO_FILE.exists():
        print(f"✗ エラー: 参照音声ファイルが見つかりません: {REF_AUDIO_FILE}")
        print(f"  参照音声ファイルを配置してください: {REF_AUDIO_FILE}")
        return False
    print(f"✓ 参照音声ファイルを確認: {REF_AUDIO_FILE}")
    return True


def load_texts_from_file(file_path: Path) -> list:
    """data.txtからテキストを読み込む"""
    if not file_path.exists():
        print(f"✗ エラー: {file_path} が見つかりません")
        return []
    
    texts = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            text = line.strip()
            if text:  # 空行をスキップ
                texts.append(text)
    
    print(f"✓ {len(texts)}件のテキストを読み込みました")
    return texts


def ensure_output_directory():
    """出力ディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ: {OUTPUT_DIR}")


def load_f5_tts_model(device: str = 'cpu') -> Tuple[Optional[object], Optional[object]]:
    """F5-TTSモデルをロード（初回のみ）"""
    global _model_obj, _vocoder
    
    if _model_obj is not None and _vocoder is not None:
        return _model_obj, _vocoder
    
    try:
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from importlib.resources import files
        import tomli
        from omegaconf import OmegaConf
        from hydra.utils import get_class
        
        # デフォルト設定ファイルのパス
        config_path = files("f5_tts").joinpath("infer/examples/basic/basic.toml")
        
        # 設定ファイルを読み込み
        with open(config_path, 'rb') as f:
            config = tomli.load(f)
        
        model_cfg = OmegaConf.create(config['model'])
        model_cls = get_class(model_cfg['_target_'])
        
        # モデル名（デフォルトはF5TTS_v1_Base）
        model_name = config.get('model_name', 'F5TTS_v1_Base')
        
        # チェックポイントパス（自動ダウンロードされる）
        ckpt_path = config.get('ckpt_path', '')
        
        print(f"\n[F5-TTS] モデルをロード中... (device={device}, model={model_name})")
        print("  注意: 初回実行時はモデルのダウンロード（数GB）が発生します")
        
        # モデルとボコーダーをロード
        _model_obj = load_model(
            model_cls=model_cls,
            model_cfg=model_cfg,
            ckpt_path=ckpt_path,
            device=device
        )
        _vocoder = load_vocoder(device=device)
        
        print("  ✓ モデルのロードが完了しました\n")
        return _model_obj, _vocoder
        
    except Exception as e:
        print(f"  ✗ モデルのロードに失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def generate_audio_with_f5_tts(
    text: str,
    output_path: Path,
    ref_audio_path: Path,
    ref_text: str,
    device: str = 'cpu'
) -> bool:
    """F5-TTSで音声を生成（参照音声を使用）"""
    try:
        from f5_tts.infer.utils_infer import infer_process
        import soundfile as sf
        
        # モデルをロード（初回のみ）
        model_obj, vocoder = load_f5_tts_model(device=device)
        if model_obj is None or vocoder is None:
            return False
        
        try:
            # 推論実行（ref.wavの声質とイントネーションを維持）
            audio_data = infer_process(
                ref_audio=str(ref_audio_path),
                ref_text=ref_text,
                gen_text=text,
                model_obj=model_obj,
                vocoder=vocoder,
                device=device
            )
            
            # 音声データを保存
            if audio_data is not None:
                sf.write(str(output_path), audio_data, 24000)  # 24kHz
                return True
            else:
                print("  ✗ 音声データが生成されませんでした")
                return False
                
        except Exception as e:
            print(f"  ✗ 音声生成エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    except Exception as e:
        print(f"  ✗ 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_audio_file(text: str, index: int) -> bool:
    """1件の音声ファイルを生成"""
    output_path = OUTPUT_DIR / f"call_{index:03d}.wav"
    
    print(f"[{index:3d}] 処理中: {text[:50]}...", end=" ", flush=True)
    
    # F5-TTSで音声生成（ref.wavの声質を維持）
    success = generate_audio_with_f5_tts(
        text=text,
        output_path=output_path,
        ref_audio_path=REF_AUDIO_FILE,
        ref_text=REF_TEXT,
        device='cpu'
    )
    
    if success:
        if output_path.exists():
            file_size = output_path.stat().st_size
            print(f"✓ 完了: {output_path.name} ({file_size:,} bytes)")
            return True
        else:
            print(f"✗ ファイルが生成されませんでした")
            return False
    else:
        print(f"✗ 音声生成に失敗しました")
        return False


def main():
    """メイン処理"""
    print("=" * 70)
    print("F5-TTS 音声生成スクリプト（参照音声クローン版）")
    print("=" * 70)
    
    # F5-TTSの利用可能性確認
    if not check_f5_tts_available():
        sys.exit(1)
    
    # 参照音声ファイルの確認
    if not check_ref_audio():
        sys.exit(1)
    
    # 出力ディレクトリ作成
    ensure_output_directory()
    
    # テキスト読み込み
    texts = load_texts_from_file(DATA_FILE)
    if not texts:
        print("✗ 処理するテキストがありません")
        sys.exit(1)
    
    # 参照テキストの表示
    print(f"\n参照テキスト: {REF_TEXT}")
    print(f"参照音声: {REF_AUDIO_FILE.name}")
    print("-" * 70)
    
    # 音声生成
    print(f"\n{len(texts)}件の音声を生成します...")
    print("注意: 初回実行時はモデルのダウンロード（数GB）が発生します")
    print("-" * 70)
    
    success_count = 0
    fail_count = 0
    
    for idx, text in enumerate(texts, 1):
        try:
            if generate_audio_file(text, idx):
                success_count += 1
            else:
                fail_count += 1
        except KeyboardInterrupt:
            print("\n\n⚠ ユーザーによって中断されました")
            break
        except Exception as e:
            print(f"\n[{idx:3d}] ✗ 予期しないエラー: {e}")
            fail_count += 1
    
    # 結果表示
    print("\n" + "=" * 70)
    print("生成完了")
    print("=" * 70)
    print(f"成功: {success_count}件")
    print(f"失敗: {fail_count}件")
    print(f"出力先: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()

