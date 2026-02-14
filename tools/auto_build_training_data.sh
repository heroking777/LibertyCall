#!/bin/bash
# 教師データ自動構築スクリプト
# 本番通話データからQwen2-Audio用教師データを自動生成

set -e

LOG_FILE="/opt/libertycall/logs/auto_training_build.log"
DATA_DIR="/opt/libertycall/training_data/qwen2_audio"
RECORDINGS_DIR="/opt/libertycall/recordings"

# ログ開始
echo "$(date '+%Y-%m-%d %H:%M:%S') - 教師データ自動構築開始" >> $LOG_FILE

# 前回実行時刻の記録ファイル
TIMESTAMP_FILE="/opt/libertycall/.last_training_build"
LAST_RUN=0
if [ -f "$TIMESTAMP_FILE" ]; then
    LAST_RUN=$(cat "$TIMESTAMP_FILE")
fi

CURRENT_TIME=$(date +%s)

# 新しい録音データを探す
NEW_ENTRIES=0
for client_dir in "$RECORDINGS_DIR"/*/; do
    client_name=$(basename "$client_dir")
    
    # whisper_testはスキップ
    if [ "$client_name" = "whisper_test" ]; then
        continue
    fi
    
    echo "クライアント $client_name を処理中..." >> $LOG_FILE
    
    for date_dir in "$client_dir"/*/; do
        if [ ! -d "$date_dir" ]; then
            continue
        fi
        
        # jsonlファイルの更新時刻をチェック
        for jsonl_file in "$date_dir"/*.jsonl; do
            if [ ! -f "$jsonl_file" ]; then
                continue
            fi
            
            file_time=$(stat -c %Y "$jsonl_file")
            
            # 前回実行より新しいファイルのみ処理
            if [ $file_time -gt $LAST_RUN ]; then
                echo "  処理中: $jsonl_file" >> $LOG_FILE
                
                # Pythonスクリプトでjsonlを処理
                python3 -c "
import json
import sys
import os

jsonl_file = '$jsonl_file'
date_dir = '$date_dir'
client_name = '$client_name'

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
                
                # 対応するwavファイル
                wav_file = f'{date_dir}/{uuid}.wav'
                
                if not os.path.exists(wav_file):
                    continue
                
                # Qwen2-Audio形式
                qwen2_entry = {
                    'audio': wav_file,
                    'text': text,
                    'client': client_name,
                    'date': os.path.basename(date_dir),
                    'uuid': uuid,
                    'source': 'auto_build',
                    'timestamp': entry.get('time', '')
                }
                
                # 出力ファイルに追記
                output_file = os.path.join('$DATA_DIR', f'{client_name}_auto_training_data.jsonl')
                with open(output_file, 'a') as out_f:
                    out_f.write(json.dumps(qwen2_entry, ensure_ascii=False) + '\n')
                
                print(f'    追加: {text}')
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f'    エラー: {e}')
                continue
                
except Exception as e:
    print(f'ファイル処理エラー: {e}')
    sys.exit(1)
"
                
                if [ $? -eq 0 ]; then
                    NEW_ENTRIES=$((NEW_ENTRIES + 1))
                fi
            fi
        done
    done
done

# 実行時刻を記録
echo $CURRENT_TIME > "$TIMESTAMP_FILE"

# 結果サマリー
echo "$(date '+%Y-%m-%d %H:%M:%S') - 教師データ自動構築完了" >> $LOG_FILE
echo "新規エントリ数: $NEW_ENTRIES" >> $LOG_FILE
echo "現在のデータ量:" >> $LOG_FILE
find "$DATA_DIR" -name "*training_data.jsonl" -exec wc -l {} \; | awk '{sum += $1} END {print "  総エントリ数: " sum}' >> $LOG_FILE

echo "---" >> $LOG_FILE

# 通知（オプション）
if [ $NEW_ENTRIES -gt 0 ]; then
    echo "教師データが $NEW_ENTRIES 件追加されました" | logger -t training_data_build
fi

exit 0
