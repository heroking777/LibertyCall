#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ステージ更新スクリプト
メール送信後にステージを更新するためのコマンドラインツール
"""

import sys
import argparse
from pathlib import Path

# スクリプトのディレクトリからcorp_collectorディレクトリに移動
script_dir = Path(__file__).parent
corp_collector_dir = script_dir.parent
sys.path.insert(0, str(corp_collector_dir))

from src.stage_manager import StageManager, STAGES, NEXT_STAGE


def main():
    parser = argparse.ArgumentParser(
        description="メール送信のステージを更新する"
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="更新するメールアドレス"
    )
    parser.add_argument(
        "--stage",
        choices=list(STAGES.keys()),
        help="設定するステージ（initial, follow1, follow2, follow3, completed）"
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="次のステージに進める"
    )
    parser.add_argument(
        "--master",
        default="data/output/master_leads.csv",
        help="マスターファイルのパス（デフォルト: data/output/master_leads.csv）"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="ステージ一覧を表示"
    )

    args = parser.parse_args()

    # 作業ディレクトリをcorp_collectorに変更
    import os
    os.chdir(corp_collector_dir)

    if args.list:
        print("利用可能なステージ:")
        for stage, description in STAGES.items():
            next_stage = NEXT_STAGE.get(stage, "なし")
            print(f"  {stage:12} - {description} (次: {next_stage})")
        return 0

    if not args.email:
        parser.error("メールアドレスが必要です（--listオプションを除く）")

    master_file = Path(args.master)
    if not master_file.exists():
        print(f"エラー: マスターファイルが見つかりません: {master_file}")
        return 1

    manager = StageManager(master_file)

    if args.next:
        # 次のステージに進める
        current_stage = manager.get_stage(args.email)
        if current_stage is None:
            print(f"エラー: メールアドレスが見つかりません: {args.email}")
            return 1

        next_stage = manager.update_stage_to_next(args.email)
        if next_stage:
            print(f"ステージ更新成功: {args.email}")
            print(f"  {current_stage} -> {next_stage}")
        else:
            print(f"ステージは既に完了しています: {args.email} (stage: {current_stage})")
    elif args.stage:
        # 指定されたステージに設定
        if manager.update_stage(args.email, args.stage):
            print(f"ステージ更新成功: {args.email} -> {args.stage}")
        else:
            print(f"エラー: ステージ更新に失敗しました: {args.email}")
            return 1
    else:
        # 現在のステージを表示
        stage = manager.get_stage(args.email)
        if stage:
            print(f"メールアドレス: {args.email}")
            print(f"現在のステージ: {stage} ({STAGES.get(stage, '不明')})")
        else:
            print(f"エラー: メールアドレスが見つかりません: {args.email}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

