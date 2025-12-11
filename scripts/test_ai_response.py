#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テキストをAICoreで処理して会話フローを検証するテストスクリプト

使い方:
    python3 scripts/test_ai_response.py <text> [call_id]
"""

import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from libertycall.gateway.ai_core import AICore

def main():
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/test_ai_response.py <text> [call_id]")
        sys.exit(1)
    
    text = sys.argv[1]
    call_id = sys.argv[2] if len(sys.argv) > 2 else "TEST_CALL"
    
    # AICoreを初期化
    try:
        ai_core = AICore()
    except Exception as e:
        print(f"❌ エラー: AICoreの初期化に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 会話処理（on_transcriptを呼び出す）
    try:
        # on_transcriptは返答テキストを返すが、ここでは状態を取得する必要がある
        reply_text = ai_core.on_transcript(call_id, text, is_final=True)
        
        # 状態を取得
        state = ai_core._get_session_state(call_id)
        phase = state.phase
        
        # 最後に使用されたテンプレートIDを取得（簡易版）
        # 実際の実装では、_generate_replyの結果から取得する必要がある
        # ここでは簡易的にログから取得するか、_generate_replyを直接呼び出す
        
        # _generate_replyを直接呼び出してテンプレートIDを取得
        reply_text, template_ids, intent, transfer_requested = ai_core._generate_reply(call_id, text)
        
        template_id_str = ",".join(template_ids) if template_ids else "NONE"
        
        # 出力フォーマット: PHASE=... TEMPLATE=... TEXT=...
        print(f"PHASE={phase} TEMPLATE={template_id_str} TEXT={reply_text or ''}")
        
    except Exception as e:
        print(f"❌ エラー: AI処理に失敗しました: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

