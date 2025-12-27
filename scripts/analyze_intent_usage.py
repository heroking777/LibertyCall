#!/usr/bin/env python3
"""
Intent使用統計を集計するスクリプト
直近30日分のログからIntentの出現回数を集計
"""
import os
import re
from collections import Counter
from datetime import datetime, timedelta
import gzip
from pathlib import Path

def extract_intent_from_line(line: str) -> str | None:
    """ログ行からIntentを抽出"""
    # パターン1: "INTENT call_id=... intent=XXX text=..."
    match = re.search(r'intent=(\w+)', line)
    if match:
        return match.group(1)
    
    # パターン2: "[INTENT] XXX" または "[INTENT] XXX: ..."
    match = re.search(r'\[INTENT\]\s+(\w+)', line)
    if match:
        return match.group(1)
    
    return None

def read_log_file(filepath: Path) -> list[str]:
    """ログファイルを読み込む（圧縮ファイルにも対応）"""
    lines = []
    try:
        if filepath.suffix == '.gz':
            with gzip.open(filepath, 'rt', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}")
    return lines

def is_recent_file(filepath: Path, days: int = 30) -> bool:
    """ファイルが指定日数以内に更新されているかチェック"""
    try:
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        cutoff = datetime.now() - timedelta(days=days)
        return mtime >= cutoff
    except:
        return True  # エラー時は含める

def analyze_intent_usage(logs_dir: str = "/opt/libertycall/logs", days: int = 30) -> dict[str, int]:
    """ログディレクトリからIntent使用統計を集計"""
    logs_path = Path(logs_dir)
    if not logs_path.exists():
        print(f"Error: Logs directory not found: {logs_dir}")
        return {}
    
    intent_counter = Counter()
    total_lines = 0
    processed_files = 0
    
    # すべてのログファイルを検索（.log と .log.gz）
    log_files = list(logs_path.glob("*.log")) + list(logs_path.glob("*.log.*.gz"))
    
    # サブディレクトリも検索
    for subdir in logs_path.iterdir():
        if subdir.is_dir():
            log_files.extend(subdir.glob("*.log"))
            log_files.extend(subdir.glob("*.log.*.gz"))
    
    print(f"Found {len(log_files)} log files")
    
    for log_file in log_files:
        # 日付フィルタリング（オプション）
        if not is_recent_file(log_file, days):
            continue
        
        lines = read_log_file(log_file)
        total_lines += len(lines)
        
        for line in lines:
            if 'INTENT' in line:
                intent = extract_intent_from_line(line)
                if intent:
                    intent_counter[intent] += 1
        
        processed_files += 1
        if processed_files % 10 == 0:
            print(f"Processed {processed_files} files...")
    
    print(f"Processed {processed_files} files, {total_lines} total lines")
    return dict(intent_counter)

def generate_markdown_report(intent_stats: dict[str, int], output_path: str):
    """Markdown形式のレポートを生成"""
    total = sum(intent_stats.values())
    
    # 出現回数でソート
    sorted_intents = sorted(intent_stats.items(), key=lambda x: x[1], reverse=True)
    
    lines = [
        "# Intent使用統計レポート",
        "",
        f"**集計期間**: 直近30日",
        f"**総Intent出現回数**: {total:,}",
        f"**集計日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Intent別出現回数",
        "",
        "| Intent | 出現回数 | 割合(%) |",
        "|--------|---------|---------|"
    ]
    
    for intent, count in sorted_intents:
        percentage = (count / total * 100) if total > 0 else 0
        lines.append(f"| {intent} | {count:,} | {percentage:.1f}% |")
    
    lines.extend([
        "",
        "## 集計方法",
        "",
        "- `/opt/libertycall/logs/` ディレクトリ内の全ログファイルを対象",
        "- `INTENT` を含む行からIntentを抽出",
        "- 直近30日以内に更新されたファイルのみを対象",
        "- 圧縮ファイル（.gz）も含めて検索",
        "",
        "## 注意事項",
        "",
        "- 同じ発話が複数回ログに記録される場合があります（ASRの部分認識など）",
        "- 実際のユニークな発話数より多い可能性があります"
    ])
    
    content = "\n".join(lines)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\nReport saved to: {output_path}")

if __name__ == "__main__":
    print("Analyzing Intent usage from logs...")
    intent_stats = analyze_intent_usage()
    
    if not intent_stats:
        print("No Intent data found in logs.")
    else:
        output_path = "/opt/libertycall/docs/INTENT_USAGE_STATS.md"
        generate_markdown_report(intent_stats, output_path)
        print(f"\nFound {len(intent_stats)} different Intents")
        print(f"Total occurrences: {sum(intent_stats.values()):,}")

