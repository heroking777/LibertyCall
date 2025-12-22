#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通話ごとのsummary.jsonから自動レポート生成（1日単位）

使い方:
    python3 scripts/generate_daily_report.py [--date YYYY-MM-DD] [--output OUTPUT_FILE]
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_summary_files(base_dir: Path, date_filter: str = None) -> List[Dict[str, Any]]:
    """
    指定日のsummary.jsonファイルを読み込む
    
    :param base_dir: ベースディレクトリ（/var/lib/libertycall/sessions）
    :param date_filter: 日付フィルタ（YYYY-MM-DD形式、Noneの場合は今日）
    :return: summary.jsonの内容のリスト
    """
    summaries = []
    
    if not base_dir.exists():
        print(f"⚠️  警告: ベースディレクトリが存在しません: {base_dir}", file=sys.stderr)
        return summaries
    
    # 日付フィルタが指定されていない場合は今日の日付を使用
    if date_filter is None:
        date_filter = datetime.now().strftime("%Y-%m-%d")
    
    # 日付ディレクトリを探索
    date_dir = base_dir / date_filter
    if not date_dir.exists():
        print(f"⚠️  警告: 日付ディレクトリが存在しません: {date_dir}", file=sys.stderr)
        return summaries
    
    # クライアントIDディレクトリを探索
    for client_dir in date_dir.iterdir():
        if not client_dir.is_dir():
            continue
        
        # セッションディレクトリを探索
        for session_dir in client_dir.glob('session_*'):
            if not session_dir.is_dir():
                continue
            
            summary_file = session_dir / "summary.json"
            if summary_file.exists():
                try:
                    with open(summary_file, 'r', encoding='utf-8') as f:
                        summary = json.load(f)
                        summaries.append(summary)
                except Exception as e:
                    print(f"⚠️  警告: summary.jsonの読み込みに失敗: {summary_file} - {e}", file=sys.stderr)
    
    return summaries


def generate_report(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    サマリーリストからレポートを生成
    
    :param summaries: summary.jsonの内容のリスト
    :return: レポートデータ（辞書）
    """
    if not summaries:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_calls": 0,
            "total_phrases": 0,
            "handoff_count": 0,
            "intents": {},
            "phases": {},
            "client_stats": {}
        }
    
    # 統計情報を集計
    total_calls = len(summaries)
    total_phrases = sum(s.get("total_phrases", 0) for s in summaries)
    handoff_count = sum(1 for s in summaries if s.get("handoff_occurred", False))
    
    intents_count = defaultdict(int)
    phases_count = defaultdict(int)
    client_stats = defaultdict(lambda: {
        "calls": 0,
        "phrases": 0,
        "handoffs": 0
    })
    
    for summary in summaries:
        client_id = summary.get("client_id", "unknown")
        client_stats[client_id]["calls"] += 1
        client_stats[client_id]["phrases"] += summary.get("total_phrases", 0)
        if summary.get("handoff_occurred", False):
            client_stats[client_id]["handoffs"] += 1
        
        # Intent集計
        for intent in summary.get("intents", []):
            intents_count[intent] += 1
        
        # Phase集計
        final_phase = summary.get("final_phase", "UNKNOWN")
        phases_count[final_phase] += 1
    
    # 日付を取得（最初のサマリーから）
    date = summaries[0].get("start_time", datetime.now().isoformat())[:10]
    
    return {
        "date": date,
        "total_calls": total_calls,
        "total_phrases": total_phrases,
        "handoff_count": handoff_count,
        "handoff_rate": round(handoff_count / total_calls * 100, 2) if total_calls > 0 else 0,
        "intents": dict(intents_count),
        "phases": dict(phases_count),
        "client_stats": dict(client_stats)
    }


def main():
    parser = argparse.ArgumentParser(description="通話ごとのsummary.jsonから自動レポート生成（1日単位）")
    parser.add_argument(
        '--date', '-d',
        type=str,
        default=None,
        help='日付（YYYY-MM-DD形式、デフォルト: 今日）'
    )
    parser.add_argument(
        '--base-dir', '-b',
        type=str,
        default='/var/lib/libertycall/sessions',
        help='セッションディレクトリのベースパス（デフォルト: /var/lib/libertycall/sessions）'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='出力ファイルのパス（デフォルト: stdout）'
    )
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir)
    summaries = load_summary_files(base_dir, args.date)
    
    if not summaries:
        print("⚠️  警告: サマリーファイルが見つかりませんでした。", file=sys.stderr)
        sys.exit(1)
    
    report = generate_report(summaries)
    
    # レポートを出力
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    
    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"✅ レポートを生成しました: {output_file}")
    else:
        print(output_text)


if __name__ == '__main__':
    main()

