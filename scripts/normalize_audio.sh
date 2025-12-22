#!/bin/bash
# LibertyCall 音声テンプレート品質向上スクリプト
# 無音除去 & 音量正規化を実行

set -e

# ログファイル
LOG_FILE="/opt/libertycall/logs/normalize_audio.log"
AUDIO_DIR="/opt/libertycall/clients/000/audio"

# ログディレクトリを作成
mkdir -p "$(dirname "$LOG_FILE")"

# ログに開始時刻を記録
echo "=========================================" >> "$LOG_FILE"
echo "音声正規化開始: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=========================================" >> "$LOG_FILE"

# ffmpegが利用可能か確認
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ エラー: ffmpeg がインストールされていません" | tee -a "$LOG_FILE"
    echo "   apt-get install ffmpeg を実行してください" | tee -a "$LOG_FILE"
    exit 1
fi

# 音声ディレクトリが存在するか確認
if [ ! -d "$AUDIO_DIR" ]; then
    echo "⚠️  警告: 音声ディレクトリが存在しません: $AUDIO_DIR" | tee -a "$LOG_FILE"
    exit 1
fi

# 処理対象のWAVファイルを検索
processed_count=0
error_count=0

find "$AUDIO_DIR" -name "*.wav" -type f | while read -r f; do
    # 既に正規化済みのファイルはスキップ（_norm.wav で終わるファイル）
    if [[ "$f" == *_norm.wav ]]; then
        continue
    fi
    
    # 出力ファイル名
    output_file="${f%.wav}_norm.wav"
    
    echo "処理中: $(basename "$f")" | tee -a "$LOG_FILE"
    
    # ffmpegで無音除去 & 音量正規化
    # silenceremove: 無音を除去（stop_periods=-1: 末尾の無音も除去、stop_threshold=-35dB: 閾値）
    # loudnorm: 音量正規化（EBU R128準拠）
    if ffmpeg -y -i "$f" \
        -af "silenceremove=stop_periods=-1:stop_threshold=-35dB:detection=peak,loudnorm" \
        "$output_file" >> "$LOG_FILE" 2>&1; then
        echo "  ✅ 完了: $(basename "$output_file")" | tee -a "$LOG_FILE"
        processed_count=$((processed_count + 1))
    else
        echo "  ❌ エラー: $(basename "$f")" | tee -a "$LOG_FILE"
        error_count=$((error_count + 1))
        # エラー時も元のファイルは残す
        rm -f "$output_file"
    fi
done

# 処理結果をログに記録
echo "=========================================" >> "$LOG_FILE"
echo "音声正規化完了: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "処理済み: $processed_count ファイル" >> "$LOG_FILE"
echo "エラー: $error_count ファイル" >> "$LOG_FILE"
echo "=========================================" >> "$LOG_FILE"

echo ""
echo "✅ 音声正規化処理が完了しました"
echo "   ログ: $LOG_FILE"
echo "   処理済み: $processed_count ファイル"
echo "   エラー: $error_count ファイル"

