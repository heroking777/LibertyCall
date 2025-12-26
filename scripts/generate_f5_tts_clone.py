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
JSON_FILE = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"  # clients/000/audio/ に保存

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


def load_texts_from_json(json_file: Path) -> dict:
    """voice_lines_000.jsonからテキストを読み込む"""
    if not json_file.exists():
        print(f"✗ エラー: {json_file} が見つかりません")
        return {}
    
    try:
        import json
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 音声IDとテキストのペアを取得
        voice_texts = {}
        for audio_id, config in data.items():
            if isinstance(config, dict) and "text" in config:
                text = config["text"].strip()
                if text:  # 空のテキストをスキップ
                    voice_texts[audio_id] = text
        
        print(f"✓ {len(voice_texts)}件のテキストを読み込みました")
        return voice_texts
    except json.JSONDecodeError as e:
        print(f"✗ JSONの解析に失敗しました: {e}")
        return {}
    except Exception as e:
        print(f"✗ ファイル読み込みエラー: {e}")
        return {}


def ensure_output_directory():
    """出力ディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ: {OUTPUT_DIR}")


def load_f5_tts_model(device: str = 'cpu', model_name: str = 'F5TTS_v1_Base', vocoder_name: str = 'vocos') -> Tuple[Optional[object], Optional[object]]:
    """F5-TTSモデルをロード（初回のみ）"""
    global _model_obj, _vocoder
    
    if _model_obj is not None and _vocoder is not None:
        return _model_obj, _vocoder
    
    try:
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from importlib.resources import files
        from omegaconf import OmegaConf
        from hydra.utils import get_class
        from cached_path import cached_path
        
        print(f"\n[F5-TTS] モデルをロード中... (device={device}, model={model_name}, vocoder={vocoder_name})")
        print("  注意: 初回実行時はモデルのダウンロード（数GB）が発生します")
        
        # モデル設定ファイルを読み込み
        model_cfg_path = files("f5_tts").joinpath(f"configs/{model_name}.yaml")
        model_cfg_full = OmegaConf.load(str(model_cfg_path))
        # model部分のみを取得（hydraメタデータを除外）
        model_cfg = model_cfg_full.model
        
        # モデルクラスを取得
        model_cls = get_class(f"f5_tts.model.{model_cfg.backbone}")
        
        # チェックポイントの設定
        repo_name, ckpt_step, ckpt_type = "F5-TTS", 1250000, "safetensors"
        
        if model_name != "F5TTS_Base":
            assert vocoder_name == model_cfg.mel_spec.mel_spec_type
        
        # 以前のモデル用のオーバーライド
        if model_name == "F5TTS_Base":
            if vocoder_name == "vocos":
                ckpt_step = 1200000
            elif vocoder_name == "bigvgan":
                model_name = "F5TTS_Base_bigvgan"
                ckpt_type = "pt"
        elif model_name == "E2TTS_Base":
            repo_name = "E2-TTS"
            ckpt_step = 1200000
        
        # チェックポイントファイルのパス（自動ダウンロード）
        ckpt_file = str(cached_path(f"hf://SWivid/{repo_name}/{model_name}/model_{ckpt_step}.{ckpt_type}"))
        
        # ボコーダー名を取得
        mel_spec_type = vocoder_name
        
        # モデルをロード（model_cfgはmodel部分のみを渡す - hydraメタデータを除外）
        # load_model内でmodel_cls(**model_cfg, ...)として展開されるため、model_cfgはmodel部分のみ
        _model_obj = load_model(
            model_cls=model_cls,
            model_cfg=model_cfg,  # model部分のみ（hydraメタデータなし）
            ckpt_path=ckpt_file,
            mel_spec_type=mel_spec_type,
            vocab_file="",  # 空文字列でデフォルト
            device=device
        )
        
        # ボコーダーをロード
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


def generate_audio_file(audio_id: str, text: str) -> bool:
    """1件の音声ファイルを生成"""
    output_path = OUTPUT_DIR / f"{audio_id}.wav"
    
    # 既存ファイルがあれば上書きするため、スキップしない
    if output_path.exists():
        print(f"[{audio_id:15s}] 上書き: {text[:50]}...", end=" ", flush=True)
    else:
        print(f"[{audio_id:15s}] 処理中: {text[:50]}...", end=" ", flush=True)
    
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
    
    # JSONからテキスト読み込み
    voice_texts = load_texts_from_json(JSON_FILE)
    if not voice_texts:
        print("✗ 処理するテキストがありません")
        sys.exit(1)
    
    # 参照テキストの表示
    print(f"\n参照テキスト: {REF_TEXT}")
    print(f"参照音声: {REF_AUDIO_FILE.name}")
    print("-" * 70)
    
    # 音声IDでソート（数値順）
    sorted_ids = sorted(voice_texts.keys(), key=lambda x: (len(x), x))
    total_count = len(sorted_ids)
    
    # 音声生成
    print(f"\n{total_count}件の音声を生成します...")
    print("注意: 初回実行時はモデルのダウンロード（数GB）が発生します")
    print("-" * 70)
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for idx, audio_id in enumerate(sorted_ids, 1):
        try:
            text = voice_texts[audio_id]
            result = generate_audio_file(audio_id, text)
            if result:
                success_count += 1
            else:
                fail_count += 1
        except KeyboardInterrupt:
            print("\n\n⚠ ユーザーによって中断されました")
            break
        except Exception as e:
            print(f"\n[{audio_id:15s}] ✗ 予期しないエラー: {e}")
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

