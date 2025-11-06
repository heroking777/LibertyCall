#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, tempfile, subprocess, os
from pathlib import Path

def agi_put(s): print(s, flush=True)
text = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
t = re.sub(r'\s+', ' ', text)
if re.search(r'(営業時間|何時|時間)', t):
    reply = '弊社の営業時間は平日10時から17時半です。'
elif re.search(r'(メール|連絡先)', t):
    reply = 'メールは info アット リバティーコール ドット ジェーピー です。'
else:
    reply = '内容を確認しました。担当者にお繋ぎします。'
agi_put(f'VERBOSE "ai_handler: reply={reply}" 1')
agi_put(f'SET VARIABLE AI_REPLY "{reply}"')
# ここでは TTS は未実装。先に占位として無音0.5秒 ulaw を生成して再生確認を行う
out = '/var/lib/asterisk/sounds/ja/ai_temp.ulaw'
Path('/var/lib/asterisk/sounds/ja').mkdir(parents=True, exist_ok=True)
# 500msの無音: soxで生成（インストール済み前提）
subprocess.run(['sox', '-n', '-r', '8000', '-e', 'u-law', '-c', '1', out, 'trim', '0.0', '0.5'], check=False)
agi_put('VERBOSE "ai_handler: synthesized stub ulaw created" 1')
