#!/usr/bin/env python3
"""
Qwen2-Audio LoRAファインチューニング用データ変換スクリプト
既存のwav+jsonlをQwen2-Audio形式に変換
"""

import json
import glob
import os
import sys
from pathlib import Path

def convert_to_qwen2_audio_format():
    """既存データをQwen2-Audio形式に変換"""
    
    # 入力データ
    whisper_files = glob.glob('/opt/libertycall/training_data/whisper/*.jsonl')
    recordings_dir = '/opt/libertycall/recordings'
    
    # 出力ディレクトリ
    output_dir = '/opt/libertycall/training_data/qwen2_audio'
    os.makedirs(output_dir, exist_ok=True)
    
    converted_data = []
    
    print("既存データをQwen2-Audio形式に変換中...")
    
    for whisper_file in whisper_files:
        print(f"処理中: {whisper_file}")
        
        with open(whisper_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    
                    audio_path = data.get('audio_file')
                    text = data.get('text', '').strip()
                    confidence = data.get('confidence', 0.0)
                    
                    if not audio_path or not text:
                        continue
                    
                    # 音声ファイルの存在確認
                    if not os.path.exists(audio_path):
                        print(f"  警告: 音声ファイルが存在しません: {audio_path}")
                        continue
                    
                    # Qwen2-Audio形式に変換
                    qwen2_entry = {
                        "audio": audio_path,
                        "text": text,
                        "confidence": confidence,
                        "source": f"whisper_{os.path.basename(whisper_file)}_{line_num}"
                    }
                    
                    converted_data.append(qwen2_entry)
                    print(f"  変換: '{text}' (confidence: {confidence:.3f})")
                    
                except json.JSONDecodeError as e:
                    print(f"  エラー: JSONデコード失敗 行{line_num}: {e}")
                    continue
    
    # 変換結果を保存
    output_file = os.path.join(output_dir, 'training_data.jsonl')
    with open(output_file, 'w') as f:
        for entry in converted_data:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    print(f"\n変換完了:")
    print(f"  - 変換エントリ数: {len(converted_data)}")
    print(f"  - 出力ファイル: {output_file}")
    
    return converted_data

def extract_from_recordings():
    """録音データから直接教師データを抽出"""
    
    recordings_dir = '/opt/libertycall/recordings'
    output_dir = '/opt/libertycall/training_data/qwen2_audio'
    
    # クライアント別に処理
    for client_dir in glob.glob(f'{recordings_dir}/*/'):
        client_name = os.path.basename(client_dir.rstrip('/'))
        
        if client_name == 'whisper_test':
            continue  # テストデータは除外
        
        print(f"\nクライアント {client_name} の録音を処理中...")
        
        # 日付別のディレクトリを処理
        for date_dir in glob.glob(f'{client_dir}/*/'):
            date_str = os.path.basename(date_dir.rstrip('/'))
            
            # jsonlとwavのペアを探す
            jsonl_files = glob.glob(f'{date_dir}/*.jsonl')
            
            for jsonl_file in jsonl_files:
                print(f"  処理中: {jsonl_file}")
                
                try:
                    with open(jsonl_file, 'r') as f:
                        for line in f:
                            try:
                                entry = json.loads(line.strip())
                                
                                if entry.get('type') != 'asr_final':
                                    continue
                                
                                text = entry.get('text', '').strip()
                                uuid = entry.get('uuid', '')
                                
                                if not text or not uuid:
                                    continue
                                
                                # 対応するwavファイルを探す
                                wav_file = f"{date_dir}/{uuid}.wav"
                                
                                if not os.path.exists(wav_file):
                                    continue
                                
                                # Qwen2-Audio形式
                                qwen2_entry = {
                                    "audio": wav_file,
                                    "text": text,
                                    "client": client_name,
                                    "date": date_str,
                                    "uuid": uuid,
                                    "source": "recording"
                                }
                                
                                # 追加
                                output_file = os.path.join(output_dir, f'{client_name}_training_data.jsonl')
                                with open(output_file, 'a') as out_f:
                                    out_f.write(json.dumps(qwen2_entry, ensure_ascii=False) + '\n')
                                
                                print(f"    追加: '{text}'")
                                
                            except json.JSONDecodeError:
                                continue
                                
                except Exception as e:
                    print(f"  エラー: {e}")
                    continue

def create_training_config():
    """Qwen2-Audioトレーニング設定ファイルを作成"""
    
    config = {
        "model_name": "Qwen/Qwen2-Audio-7B",
        "data_path": "/opt/libertycall/training_data/qwen2_audio",
        "output_dir": "/opt/libertycall/models/qwen2_audio_lora",
        "training_args": {
            "per_device_train_batch_size": 2,
            "gradient_accumulation_steps": 4,
            "learning_rate": 2e-4,
            "num_train_epochs": 3,
            "lr_scheduler_type": "cosine",
            "warmup_ratio": 0.1,
            "logging_steps": 10,
            "save_steps": 500,
            "eval_steps": 500,
            "save_total_limit": 2,
            "load_best_model_at_end": True,
            "metric_for_best_model": "eval_wer",
            "greater_is_better": False,
            "fp16": True,
            "gradient_checkpointing": True,
            "dataloader_num_workers": 4,
            "remove_unused_columns": False
        },
        "lora_config": {
            "r": 16,
            "lora_alpha": 32,
            "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
            "lora_dropout": 0.1,
            "bias": "none",
            "task_type": "ASR"
        }
    }
    
    config_file = '/opt/libertycall/training_data/qwen2_audio/training_config.json'
    with open(config_file, 'w') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"トレーニング設定を保存: {config_file}")

def main():
    """メイン処理"""
    print("Qwen2-Audio LoRAファインチューニングデータ準備")
    print("=" * 50)
    
    # 1. 既存Whisperデータの変換
    converted_data = convert_to_qwen2_audio_format()
    
    # 2. 録音データからの抽出
    extract_from_recordings()
    
    # 3. トレーニング設定の作成
    create_training_config()
    
    print("\n準備完了！")
    print("GPU調達後に以下のコマンドでトレーニング開:")
    print("python3 /opt/libertycall/scripts/train_qwen2_audio.py")

if __name__ == "__main__":
    main()
