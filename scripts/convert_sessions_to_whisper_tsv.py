#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
録音とASRログをWhisper学習用TSVに自動変換するスクリプト

使い方:
    python3 scripts/convert_sessions_to_whisper_tsv.py [--output OUTPUT_FILE] [--date DATE] [--client-id CLIENT_ID]

出力例:
    /var/lib/libertycall/sessions/2025-12-16/000/session_20251216_210045/audio/caller.wav    もしもし ホームページ見ました
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_transcript_jsonl(transcript_file: Path) -> List[str]:
    """
    transcript.jsonlからis_final=Trueのテキストを抽出
    
    :param transcript_file: transcript.jsonlファイルのパス
    :return: テキストのリスト
    """
    texts = []
    if not transcript_file.exists():
        return texts
    
    try:
        with open(transcript_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get('type') == 'on_transcript' and event.get('is_final', False):
                        text = event.get('text', '').strip()
                        if text:
                            texts.append(text)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"⚠️  警告: transcript.jsonlの読み込みに失敗: {transcript_file} - {e}", file=sys.stderr)
    
    return texts


def find_session_directories(
    base_dir: Path,
    date_filter: Optional[str] = None,
    client_id_filter: Optional[str] = None
) -> List[Path]:
    """
    セッションディレクトリを再帰的に探索
    
    :param base_dir: ベースディレクトリ（/var/lib/libertycall/sessions）
    :param date_filter: 日付フィルタ（YYYY-MM-DD形式、Noneの場合は全期間）
    :param client_id_filter: クライアントIDフィルタ（Noneの場合は全クライアント）
    :return: セッションディレクトリのリスト
    """
    session_dirs = []
    
    if not base_dir.exists():
        print(f"⚠️  警告: ベースディレクトリが存在しません: {base_dir}", file=sys.stderr)
        return session_dirs
    
    # 日付ディレクトリを探索
    date_dirs = [d for d in base_dir.iterdir() if d.is_dir() and d.name.count('-') == 2]
    
    for date_dir in date_dirs:
        # 日付フィルタ適用
        if date_filter and date_dir.name != date_filter:
            continue
        
        # クライアントIDディレクトリを探索
        client_dirs = [d for d in date_dir.iterdir() if d.is_dir()]
        
        for client_dir in client_dirs:
            # クライアントIDフィルタ適用
            if client_id_filter and client_dir.name != client_id_filter:
                continue
            
            # セッションディレクトリを探索
            session_pattern = client_dir.glob('session_*')
            for session_dir in session_pattern:
                if session_dir.is_dir():
                    session_dirs.append(session_dir)
    
    return sorted(session_dirs)


def convert_session_to_tsv_entry(session_dir: Path) -> Optional[Tuple[str, str]]:
    """
    セッションディレクトリからTSVエントリを生成
    
    :param session_dir: セッションディレクトリのパス
    :return: (音声ファイルパス, テキスト) のタプル、またはNone（エラー時）
    """
    audio_file = session_dir / "audio" / "caller.wav"
    transcript_file = session_dir / "transcript.jsonl"
    
    # 音声ファイルの存在確認
    if not audio_file.exists():
        return None
    
    # transcript.jsonlからテキストを抽出
    texts = load_transcript_jsonl(transcript_file)
    
    if not texts:
        return None
    
    # すべてのテキストを結合（スペース区切り）
    combined_text = " ".join(texts)
    
    # 音声ファイルの絶対パスとテキストを返す
    return (str(audio_file.resolve()), combined_text)


def convert_sessions_to_tsv(
    base_dir: Path,
    output_file: Path,
    date_filter: Optional[str] = None,
    client_id_filter: Optional[str] = None,
    append: bool = False
) -> None:
    """
    セッションディレクトリを探索してTSVファイルを生成
    
    :param base_dir: ベースディレクトリ（/var/lib/libertycall/sessions）
    :param output_file: 出力TSVファイルのパス
    :param date_filter: 日付フィルタ（YYYY-MM-DD形式、Noneの場合は全期間）
    :param client_id_filter: クライアントIDフィルタ（Noneの場合は全クライアント）
    :param append: 既存ファイルに追記するかどうか
    """
    # セッションディレクトリを探索
    session_dirs = find_session_directories(base_dir, date_filter, client_id_filter)
    
    if not session_dirs:
        print(f"⚠️  警告: セッションディレクトリが見つかりませんでした。", file=sys.stderr)
        return
    
    print(f"📁 セッションディレクトリを {len(session_dirs)} 個見つけました。")
    
    # 既存のエントリを読み込む（追記モードの場合）
    existing_entries = set()
    if append and output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        parts = line.split('\t', 1)
                        if len(parts) == 2:
                            existing_entries.add(parts[0])  # 音声ファイルパスを記録
        except Exception as e:
            print(f"⚠️  警告: 既存TSVファイルの読み込みに失敗: {e}", file=sys.stderr)
    
    # TSVエントリを生成
    new_entries = []
    processed_count = 0
    skipped_count = 0
    
    for session_dir in session_dirs:
        entry = convert_session_to_tsv_entry(session_dir)
        if entry:
            audio_path, text = entry
            # 既存エントリをスキップ（追記モードの場合）
            if audio_path in existing_entries:
                skipped_count += 1
                continue
            new_entries.append((audio_path, text))
            processed_count += 1
        else:
            skipped_count += 1
    
    if not new_entries:
        print(f"⚠️  警告: 新しいエントリが見つかりませんでした。", file=sys.stderr)
        return
    
    # TSVファイルに書き込み
    mode = 'a' if append else 'w'
    try:
        with open(output_file, mode, encoding='utf-8') as f:
            for audio_path, text in new_entries:
                # TSV形式: 音声ファイルパス\tテキスト
                f.write(f"{audio_path}\t{text}\n")
        
        print(f"✅ TSVファイルを生成しました: {output_file}")
        print(f"   処理済み: {processed_count} エントリ")
        if skipped_count > 0:
            print(f"   スキップ: {skipped_count} エントリ（既存またはデータなし）")
    except Exception as e:
        print(f"❌ エラー: TSVファイルの書き込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="録音とASRログをWhisper学習用TSVに自動変換"
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='/var/lib/libertycall/training_data.tsv',
        help='出力TSVファイルのパス（デフォルト: /var/lib/libertycall/training_data.tsv）'
    )
    parser.add_argument(
        '--base-dir', '-b',
        type=str,
        default='/var/lib/libertycall/sessions',
        help='セッションディレクトリのベースパス（デフォルト: /var/lib/libertycall/sessions）'
    )
    parser.add_argument(
        '--date', '-d',
        type=str,
        default=None,
        help='日付フィルタ（YYYY-MM-DD形式、例: 2025-12-16）'
    )
    parser.add_argument(
        '--client-id', '-c',
        type=str,
        default=None,
        help='クライアントIDフィルタ（例: 000）'
    )
    parser.add_argument(
        '--append', '-a',
        action='store_true',
        help='既存TSVファイルに追記する（デフォルト: 上書き）'
    )
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir)
    output_file = Path(args.output)
    
    # 出力ディレクトリを作成
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"🔍 セッションディレクトリを探索中: {base_dir}")
    if args.date:
        print(f"   日付フィルタ: {args.date}")
    if args.client_id:
        print(f"   クライアントIDフィルタ: {args.client_id}")
    print(f"📝 出力先: {output_file}")
    if args.append:
        print(f"   モード: 追記")
    else:
        print(f"   モード: 上書き")
    
    convert_sessions_to_tsv(
        base_dir=base_dir,
        output_file=output_file,
        date_filter=args.date,
        client_id_filter=args.client_id,
        append=args.append
    )


if __name__ == '__main__':
    main()

