#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slack/Discord Webhook通知スクリプト

使い方:
    python3 scripts/send_webhook_notification.py --event ASR_START --call-id <uuid> --message "ASR started"
    
環境変数:
    LC_SLACK_WEBHOOK_URL: Slack Webhook URL
    LC_DISCORD_WEBHOOK_URL: Discord Webhook URL
"""

import sys
import os
import argparse
import json
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("⚠️  警告: requests パッケージがインストールされていません。", file=sys.stderr)
    print("   pip install requests を実行してください。", file=sys.stderr)


def send_slack_webhook(webhook_url: str, message: str, event_type: str = None, call_id: str = None) -> bool:
    """
    Slack Webhookに通知を送信
    
    :param webhook_url: Slack Webhook URL
    :param message: メッセージ内容
    :param event_type: イベントタイプ（オプション）
    :param call_id: 通話ID（オプション）
    :return: 送信に成功したかどうか
    """
    if not REQUESTS_AVAILABLE:
        return False
    
    try:
        payload = {
            "text": message
        }
        
        # イベントタイプとcall_idがある場合は詳細情報を追加
        if event_type or call_id:
            fields = []
            if event_type:
                fields.append({"title": "Event", "value": event_type, "short": True})
            if call_id:
                fields.append({"title": "Call ID", "value": call_id[:20], "short": True})
            
            payload["attachments"] = [{
                "color": "good" if event_type in ("ASR_START", "FLOW_PHASE") else "warning",
                "fields": fields
            }]
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ エラー: Slack Webhook送信に失敗しました: {e}", file=sys.stderr)
        return False


def send_discord_webhook(webhook_url: str, message: str, event_type: str = None, call_id: str = None) -> bool:
    """
    Discord Webhookに通知を送信
    
    :param webhook_url: Discord Webhook URL
    :param message: メッセージ内容
    :param event_type: イベントタイプ（オプション）
    :param call_id: 通話ID（オプション）
    :return: 送信に成功したかどうか
    """
    if not REQUESTS_AVAILABLE:
        return False
    
    try:
        # Discordのメッセージ形式（1行フォーマット）
        content = message
        if event_type:
            content = f"**[{event_type}]** {message}"
        if call_id:
            content += f" `call_id={call_id[:20]}`"
        
        payload = {
            "content": content
        }
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ エラー: Discord Webhook送信に失敗しました: {e}", file=sys.stderr)
        return False


def send_notification(event_type: str, message: str, call_id: str = None) -> bool:
    """
    Slack/Discord Webhookに通知を送信（環境変数からURLを取得）
    
    :param event_type: イベントタイプ
    :param message: メッセージ内容
    :param call_id: 通話ID（オプション）
    :return: 送信に成功したかどうか
    """
    slack_url = os.getenv("LC_SLACK_WEBHOOK_URL")
    discord_url = os.getenv("LC_DISCORD_WEBHOOK_URL")
    
    success = False
    
    if slack_url:
        if send_slack_webhook(slack_url, message, event_type, call_id):
            success = True
    
    if discord_url:
        if send_discord_webhook(discord_url, message, event_type, call_id):
            success = True
    
    if not slack_url and not discord_url:
        print("⚠️  警告: LC_SLACK_WEBHOOK_URL または LC_DISCORD_WEBHOOK_URL が設定されていません。", file=sys.stderr)
    
    return success


def main():
    parser = argparse.ArgumentParser(description="Slack/Discord Webhook通知")
    parser.add_argument('--event', '-e', type=str, required=True, help='イベントタイプ（例: ASR_START, INTENT, FLOW_PHASE）')
    parser.add_argument('--call-id', '-c', type=str, default=None, help='通話ID')
    parser.add_argument('--message', '-m', type=str, required=True, help='メッセージ内容')
    
    args = parser.parse_args()
    
    success = send_notification(args.event, args.message, args.call_id)
    
    if success:
        print(f"✅ 通知を送信しました: {args.event}")
        sys.exit(0)
    else:
        print(f"❌ 通知の送信に失敗しました: {args.event}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

