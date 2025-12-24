#!/bin/bash
# ASRテスト用環境変数設定スクリプト

echo "=========================================="
echo "ASRテスト用環境変数設定"
echo "=========================================="
echo ""

# Google認証情報のパスを確認
GOOGLE_CRED_PATH="/opt/libertycall/key/google_tts.json"

if [ -f "$GOOGLE_CRED_PATH" ]; then
    echo "✅ Google認証ファイルが見つかりました: $GOOGLE_CRED_PATH"
    export GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_CRED_PATH"
    echo "✅ GOOGLE_APPLICATION_CREDENTIALS を設定しました"
else
    echo "⚠️  Google認証ファイルが見つかりません: $GOOGLE_CRED_PATH"
    echo "   別のパスを指定する場合は、以下を実行してください:"
    echo "   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json"
fi

echo ""
echo "現在の環境変数:"
echo "  GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS:-未設定}"
echo ""
echo "この環境変数を永続化するには、以下を ~/.bashrc または /etc/environment に追加:"
echo "  export GOOGLE_APPLICATION_CREDENTIALS=\"$GOOGLE_CRED_PATH\""
echo ""

