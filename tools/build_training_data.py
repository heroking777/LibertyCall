#!/usr/bin/env python3
"""
教師データ自動生成スクリプト
JSONLからasr_finalとresponseのペアを抽出して、Whisper用とLLM用のデータセットを生成
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

def parse_jsonl(file_path: str) -> List[Dict]:
    """JSONLファイルをパース"""
    data = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []
    return data

def extract_dialogue_pairs(data: List[Dict], min_confidence: float = 0.7) -> List[Dict]:
    """対話ペアを抽出"""
    pairs = []
    
    # responseと次のasr_finalをペアリング
    for i in range(len(data)):
        current = data[i]
        
        # responseイベントを探す
        if current.get('type') == 'response':
            response_text = current.get('text', '').strip()
            audio_ids = current.get('audio_ids', [])
            response_time = current.get('time', '')
            
            # 次のasr_finalを探す
            for j in range(i + 1, len(data)):
                next_item = data[j]
                if next_item.get('type') == 'asr_final':
                    asr_text = next_item.get('text', '').strip()
                    confidence = next_item.get('confidence', 0.0)
                    asr_time = next_item.get('time', '')
                    
                    # 品質フィルタリング
                    if (confidence >= min_confidence and 
                        len(asr_text) > 0 and 
                        len(response_text) > 0):
                        
                        pairs.append({
                            'user_input': asr_text,
                            'system_response': response_text,
                            'confidence': confidence,
                            'audio_ids': audio_ids,
                            'user_time': asr_time,
                            'system_time': response_time
                        })
                    break
    
    return pairs

def find_wav_file(jsonl_path: str) -> Optional[str]:
    """対応するWAVファイルを探す"""
    uuid = Path(jsonl_path).stem
    wav_path = Path(jsonl_path).parent / f"{uuid}.wav"
    
    if wav_path.exists():
        return str(wav_path)
    return None

def generate_whisper_dataset(pairs: List[Dict], wav_path: str, output_dir: str):
    """Whisper用データセットを生成"""
    whisper_dir = Path(output_dir) / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)
    
    # Whisper用のメタデータファイル
    metadata = []
    
    for pair in pairs:
        metadata.append({
            'audio_file': wav_path,
            'text': pair['user_input'],
            'confidence': pair['confidence'],
            'timestamp': pair['user_time']
        })
    
    # JSONL形式で出力
    output_file = whisper_dir / f"{Path(wav_path).stem}_metadata.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in metadata:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"Whisper dataset: {len(metadata)} items -> {output_file}")

def generate_llm_dataset(pairs: List[Dict], output_dir: str, client_id: str):
    """LLM用データセットを生成"""
    llm_dir = Path(output_dir) / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    
    # LLM用の対話データ
    conversations = []
    
    for pair in pairs:
        # instruction-following形式
        conversation = {
            'instruction': '以下のユーザーの発話に適切に応答してください。',
            'input': pair['user_input'],
            'output': pair['system_response'],
            'confidence': pair['confidence'],
            'client_id': client_id
        }
        conversations.append(conversation)
    
    # JSONL形式で出力
    output_file = llm_dir / f"conversations_{client_id}.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in conversations:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"LLM dataset: {len(conversations)} conversations -> {output_file}")

def process_recordings_directory(recordings_dir: str, output_dir: str):
    """録音ディレクトリを処理"""
    recordings_path = Path(recordings_dir)
    total_pairs = 0
    
    # 各クライアントディレクトリを処理
    for client_dir in recordings_path.iterdir():
        if not client_dir.is_dir() or client_dir.name.startswith('.'):
            continue
        
        client_id = client_dir.name
        print(f"\nProcessing client: {client_id}")
        
        # 各日付ディレクトリを処理
        for date_dir in client_dir.iterdir():
            if not date_dir.is_dir():
                continue
            
            # JSONLファイルを処理
            for jsonl_file in date_dir.glob("*.jsonl"):
                print(f"Processing: {jsonl_file}")
                
                # 対応するWAVファイルを探す
                wav_path = find_wav_file(str(jsonl_file))
                if not wav_path:
                    print(f"  Warning: No WAV file found for {jsonl_file}")
                    continue
                
                # JSONLをパース
                data = parse_jsonl(str(jsonl_file))
                if not data:
                    continue
                
                # 対話ペアを抽出
                pairs = extract_dialogue_pairs(data)
                if not pairs:
                    continue
                
                total_pairs += len(pairs)
                
                # Whisper用データセットを生成
                generate_whisper_dataset(pairs, wav_path, output_dir)
                
                # LLM用データセットを生成
                generate_llm_dataset(pairs, output_dir, client_id)
    
    print(f"\nTotal pairs extracted: {total_pairs}")
    return total_pairs

def main():
    """メイン処理"""
    recordings_dir = "/opt/libertycall/recordings"
    output_dir = "/opt/libertycall/training_data"
    
    print("教師データ自動生成スクリプト")
    print(f"録音ディレクトリ: {recordings_dir}")
    print(f"出力ディレクトリ: {output_dir}")
    
    if not os.path.exists(recordings_dir):
        print(f"Error: 録音ディレクトリが存在しません: {recordings_dir}")
        sys.exit(1)
    
    # 録音ディレクトリを処理
    total_pairs = process_recordings_directory(recordings_dir, output_dir)
    
    print(f"\n完了！")
    print(f"合計対話ペア数: {total_pairs}")
    print(f"データセット出力先: {output_dir}")

if __name__ == "__main__":
    main()
