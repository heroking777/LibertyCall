#!/bin/bash
# ASRエラー発生時の挙動確認テストスクリプト
# 注意: 本番環境で実行する場合は、別ポートのテスト用gatewayを使用してください

set -e

echo "=== STEP 3: ASRエラー発生時の挙動確認テスト ==="
echo ""

# 0) venvを有効化
source /opt/libertycall/venv/bin/activate

# 1) 現在の環境変数をバックアップ（元に戻すため）
ORIG_GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-}"
ORIG_LC_GOOGLE_CREDENTIALS_PATH="${LC_GOOGLE_CREDENTIALS_PATH:-}"
ORIG_LC_GOOGLE_PROJECT_ID="${LC_GOOGLE_PROJECT_ID:-}"

# 2) 無効な認証パスを設定（ASRエラーを意図的に発生させる）
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/invalid_dummy.json"
export LC_GOOGLE_CREDENTIALS_PATH="/opt/libertycall/key/invalid_dummy.json"
export LC_GOOGLE_PROJECT_ID="libertycall-main"

echo "環境変数を設定しました:"
echo "  GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
echo "  LC_GOOGLE_CREDENTIALS_PATH=${LC_GOOGLE_CREDENTIALS_PATH}"
echo "  LC_GOOGLE_PROJECT_ID=${LC_GOOGLE_PROJECT_ID}"
echo ""

# 3) ログ監視用のコマンドを表示
echo "=== ログ監視コマンド（別ターミナルで実行） ==="
echo "tail -f /opt/libertycall/logs/gateway.log 2>/dev/null | grep -E 'ASR_ERROR|ASR_GOOGLE_ERROR|ASR_ERROR_HANDLER|STREAM_WORKER_CRASHED|TRANSFER'"
echo ""

# 4) テスト用gatewayの起動方法を表示
echo "=== テスト用gateway起動方法 ==="
echo "cd /opt/libertycall"
echo "python gateway/realtime_gateway.py"
echo ""
echo "※ 本番環境で実行する場合は、別ポートで起動するか、"
echo "   テスト環境で実行してください。"
echo ""

# 5) 環境変数を元に戻す関数
cleanup() {
    echo ""
    echo "=== 環境変数を元に戻します ==="
    if [ -n "$ORIG_GOOGLE_APPLICATION_CREDENTIALS" ]; then
        export GOOGLE_APPLICATION_CREDENTIALS="$ORIG_GOOGLE_APPLICATION_CREDENTIALS"
    else
        unset GOOGLE_APPLICATION_CREDENTIALS
    fi
    
    if [ -n "$ORIG_LC_GOOGLE_CREDENTIALS_PATH" ]; then
        export LC_GOOGLE_CREDENTIALS_PATH="$ORIG_LC_GOOGLE_CREDENTIALS_PATH"
    else
        unset LC_GOOGLE_CREDENTIALS_PATH
    fi
    
    if [ -n "$ORIG_LC_GOOGLE_PROJECT_ID" ]; then
        export LC_GOOGLE_PROJECT_ID="$ORIG_LC_GOOGLE_PROJECT_ID"
    else
        unset LC_GOOGLE_PROJECT_ID
    fi
    
    echo "環境変数を元に戻しました。"
}

# シグナルハンドラを設定（Ctrl+Cで環境変数を元に戻す）
trap cleanup EXIT INT TERM

echo "=== テスト準備完了 ==="
echo ""
echo "次のステップ:"
echo "1. 別ターミナルでログ監視コマンドを実行"
echo "2. このターミナルでテスト用gatewayを起動"
echo "3. テスト電話をかけて、ASRエラー時の挙動を確認"
echo ""
echo "確認項目:"
echo "- AIの発話内容（「うまくお話をお伺いできませんでしたので…」）"
echo "- 転送コールバックが呼ばれたログ（TRANSFER_CALLBACK_*）"
echo "- 1コール中に何回ASRエラー→転送フローが起きるか"
echo "- ネットワーク切断/Google側障害時でも全通話が一斉に転送されないか"
echo ""
echo "テストが終わったら、Ctrl+Cを押して環境変数を元に戻してください。"
echo ""
echo "このシェルでgatewayを起動する場合は、以下のコマンドを実行してください:"
echo ""
echo "  python gateway/realtime_gateway.py"
echo ""
echo "Enterキーを押すと、このスクリプトは終了します（環境変数は元に戻ります）。"
echo "gatewayを起動する場合は、Enterを押さずに上記コマンドを実行してください。"
read -r

