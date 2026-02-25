#!/usr/bin/env python3
"""通話ログ+録音から Whisper ファインチューニング用データセットを生成"""
import json
import os
import glob
import subprocess
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

RECORDINGS_DIR = "/opt/libertycall/recordings"
DATASET_DIR = "/opt/libertycall/training_data"
SEGMENTS_DIR = os.path.join(DATASET_DIR, "segments")

os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(SEGMENTS_DIR, exist_ok=True)


def parse_jsonl(jsonl_path):
    """JSONLから教師データペア（音声区間 + テキスト + 応答ID）を抽出"""
    entries = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    pairs = []
    current_interim_start = None
    current_final_text = None
    current_response_id = None
    
    for i, entry in enumerate(entries):
        etype = entry.get("type", "")
        
        # interim開始時刻を記録
        if etype == "asr_interim" and current_interim_start is None:
            current_interim_start = entry.get("time")
        
        # final確定
        if etype == "asr_final":
            current_final_text = entry.get("text", "").strip()
            final_time = entry.get("time")
            confidence = entry.get("confidence", 0)
            
            # 対応するresponseを探す（finalの前後5エントリ以内）
            response_id = None
            for j in range(max(0, i-5), min(len(entries), i+5)):
                if entries[j].get("type") == "response":
                    audio_ids = entries[j].get("audio_ids", [])
                    if audio_ids:
                        response_id = audio_ids[0]
                    break
            
            if current_final_text and current_interim_start and confidence > 0.5:
                pairs.append({
                    "start_time": current_interim_start,
                    "end_time": final_time,
                    "text": current_final_text,
                    "response_id": response_id,
                    "confidence": confidence
                })
            
            current_interim_start = None
            current_final_text = None
    
    return pairs


def extract_audio_segment(wav_path, start_time_str, end_time_str, output_path, call_start_str):
    """WAVから指定区間を切り出し（ffmpeg使用）"""
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        call_start = datetime.strptime(call_start_str, fmt)
        seg_start = datetime.strptime(start_time_str, fmt)
        seg_end = datetime.strptime(end_time_str, fmt)
        
        offset = (seg_start - call_start).total_seconds()
        duration = (seg_end - seg_start).total_seconds()
        
        # 前後に0.3秒のマージン
        offset = max(0, offset - 0.3)
        duration = duration + 0.6
        
        cmd = [
            "ffmpeg", "-y", "-i", wav_path,
            "-ss", str(offset), "-t", str(duration),
            "-ar", "16000", "-ac", "1", "-f", "wav",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.returncode == 0
    except Exception as e:
        logger.warning("ffmpeg error: %s", e)
        return False


def process_session(jsonl_path, wav_path):
    """1通話セッションを処理"""
    pairs = parse_jsonl(jsonl_path)
    if not pairs:
        return []
    
    # call_start時刻を取得
    call_start = None
    with open(jsonl_path) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry.get("type") == "call_start":
                call_start = entry.get("time")
                break
    
    if not call_start:
        return []
    
    uuid = os.path.basename(jsonl_path).replace(".jsonl", "")
    results = []
    
    for idx, pair in enumerate(pairs):
        seg_filename = f"{uuid}_{idx:03d}.wav"
        seg_path = os.path.join(SEGMENTS_DIR, seg_filename)
        
        if os.path.exists(wav_path):
            extracted = extract_audio_segment(
                wav_path, pair["start_time"], pair["end_time"],
                seg_path, call_start
            )
        else:
            extracted = False
        
        results.append({
            "audio_file": seg_filename if extracted else None,
            "text": pair["text"],
            "response_id": pair["response_id"],
            "confidence": pair["confidence"],
            "uuid": uuid,
            "start_time": pair["start_time"],
            "end_time": pair["end_time"]
        })
    
    return results


def build_dataset(days_back=30):
    """過去N日分のデータからデータセットを構築"""
    all_data = []
    jsonl_files = sorted(glob.glob(f"{RECORDINGS_DIR}/**/*.jsonl", recursive=True))
    
    logger.info("Found %d JSONL files", len(jsonl_files))
    
    for jsonl_path in jsonl_files:
        wav_path = jsonl_path.replace(".jsonl", ".wav")
        try:
            results = process_session(jsonl_path, wav_path)
            all_data.extend(results)
        except Exception as e:
            logger.warning("Error processing %s: %s", jsonl_path, e)
    
    # データセットを保存
    dataset_path = os.path.join(DATASET_DIR, "dataset.jsonl")
    with open(dataset_path, 'w', encoding='utf-8') as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    # 統計
    total = len(all_data)
    with_audio = sum(1 for d in all_data if d["audio_file"])
    with_response = sum(1 for d in all_data if d["response_id"])
    
    logger.info("=== Dataset Summary ===")
    logger.info("Total pairs: %d", total)
    logger.info("With audio segments: %d", with_audio)
    logger.info("With response IDs: %d", with_response)
    logger.info("Saved to: %s", dataset_path)
    
    # テキストのみのデータセット（LLM学習用）
    llm_dataset_path = os.path.join(DATASET_DIR, "llm_training.jsonl")
    with open(llm_dataset_path, 'w', encoding='utf-8') as f:
        for item in all_data:
            if item["text"] and item["response_id"]:
                f.write(json.dumps({
                    "input": item["text"],
                    "output": item["response_id"]
                }, ensure_ascii=False) + "\n")
    
    llm_count = sum(1 for d in all_data if d["text"] and d["response_id"])
    logger.info("LLM training pairs: %d -> %s", llm_count, llm_dataset_path)
    
    return all_data


if __name__ == "__main__":
    build_dataset()
