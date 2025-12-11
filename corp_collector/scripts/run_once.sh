#!/bin/bash
# 法人向けメールアドレス収集バッチ実行スクリプト
# cronから実行する場合のエントリーポイント
# 毎日2時に100クエリ実行して、本リストに追記（重複チェック付き）

# プロジェクトルートに移動
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# .envファイルを読み込む（/opt/libertycall/.env）
if [ -f "/opt/libertycall/.env" ]; then
    set -a
    source /opt/libertycall/.env
    set +a
fi

# Python環境のパス（必要に応じて調整）
# 仮想環境を使用する場合:
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
fi

# メインスクリプトを実行（100クエリ制限はsettings.tomlのdaily_query_limit=100で制御）
python -m src.main "$@"

exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "エラー: バッチ処理が失敗しました (終了コード: $exit_code)" >&2
    exit $exit_code
fi

# データ収集が成功したら、本リストに追記（重複チェック付き）
echo "本リストへの追記を開始します..."
python3 scripts/append_to_master.py

append_exit_code=$?
if [ $append_exit_code -ne 0 ]; then
    echo "警告: 本リストへの追記中にエラーが発生しました (終了コード: $append_exit_code)" >&2
    # 追記エラーは警告として扱い、全体の処理は成功とする
fi

echo "処理が完了しました"

