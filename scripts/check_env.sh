#!/bin/bash
# LibertyCall ローンチ前環境確認スクリプト
# FreeSWITCH動作確認、パーミッション確認、バックアップテストを一括実行

set -e

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# チェック結果
CHECKS_PASSED=0
CHECKS_FAILED=0

echo "========================================="
echo "LibertyCall ローンチ前環境確認"
echo "========================================="
echo ""

# ============================================
# ① FreeSWITCH 側の録音とESL通信の最終確認
# ============================================
echo "【①】FreeSWITCH 動作確認"
echo "------------------------"

# FreeSWITCHプロセス確認
if pgrep -f freeswitch > /dev/null; then
    echo -e "${GREEN}✅ FreeSWITCH プロセス: 実行中${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo -e "${RED}❌ FreeSWITCH プロセス: 停止中${NC}"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

# FreeSWITCH UDPポート確認
if sudo ss -ulpn 2>/dev/null | grep -q freeswitch; then
    echo -e "${GREEN}✅ FreeSWITCH UDPポート: リッスン中${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo -e "${YELLOW}⚠️  FreeSWITCH UDPポート: 確認できませんでした${NC}"
    echo "   (FreeSWITCHが起動していない可能性があります)"
fi

# fs_cli接続確認
if command -v fs_cli &> /dev/null; then
    if sudo fs_cli -x "status" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ FreeSWITCH ESL接続: 正常${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo -e "${RED}❌ FreeSWITCH ESL接続: 失敗${NC}"
        CHECKS_FAILED=$((CHECKS_FAILED + 1))
    fi
else
    echo -e "${YELLOW}⚠️  fs_cli コマンドが見つかりません${NC}"
fi

# 録音ディレクトリ確認
RECORD_DIR="/var/lib/libertycall/sessions"
if [ -d "$RECORD_DIR" ]; then
    echo -e "${GREEN}✅ 録音ディレクトリ: 存在 ($RECORD_DIR)${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    
    # 今日のディレクトリが作成可能か確認
    TODAY_DIR="$RECORD_DIR/$(date +%Y-%m-%d)"
    if mkdir -p "$TODAY_DIR" 2>/dev/null; then
        echo -e "${GREEN}✅ 録音ディレクトリ: 書き込み可能${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo -e "${RED}❌ 録音ディレクトリ: 書き込み不可${NC}"
        CHECKS_FAILED=$((CHECKS_FAILED + 1))
    fi
else
    echo -e "${RED}❌ 録音ディレクトリ: 存在しません ($RECORD_DIR)${NC}"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

echo ""

# ============================================
# ② ログ・パーミッション確認
# ============================================
echo "【②】ログ・パーミッション確認"
echo "------------------------"

# パーミッション修正（必要に応じて）
echo "パーミッションを確認・修正中..."

# /var/lib/libertycall のパーミッション
if [ -d "/var/lib/libertycall" ]; then
    if sudo chown -R freeswitch:freeswitch /var/lib/libertycall 2>/dev/null; then
        echo -e "${GREEN}✅ /var/lib/libertycall 所有者: freeswitch:freeswitch${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo -e "${YELLOW}⚠️  /var/lib/libertycall 所有者変更: スキップ（freeswitchユーザーが存在しない可能性）${NC}"
    fi
    
    if sudo chmod -R 750 /var/lib/libertycall 2>/dev/null; then
        echo -e "${GREEN}✅ /var/lib/libertycall パーミッション: 750${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo -e "${YELLOW}⚠️  /var/lib/libertycall パーミッション変更: スキップ${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  /var/lib/libertycall ディレクトリが存在しません${NC}"
fi

# ログファイルのパーミッション
LOG_DIR="/opt/libertycall/logs"
if [ -d "$LOG_DIR" ]; then
    if sudo chmod 640 "$LOG_DIR"/*.log 2>/dev/null; then
        echo -e "${GREEN}✅ ログファイル パーミッション: 640${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
    else
        echo -e "${YELLOW}⚠️  ログファイル パーミッション変更: 一部スキップ${NC}"
    fi
    
    # runtime.logの存在確認
    if [ -f "$LOG_DIR/runtime.log" ]; then
        echo -e "${GREEN}✅ runtime.log: 存在${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
        
        # runtime.logに書き込みテスト
        if echo "[SYSTEM] Environment check: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_DIR/runtime.log" 2>/dev/null; then
            echo -e "${GREEN}✅ runtime.log: 書き込み可能${NC}"
            CHECKS_PASSED=$((CHECKS_PASSED + 1))
        else
            echo -e "${RED}❌ runtime.log: 書き込み不可${NC}"
            CHECKS_FAILED=$((CHECKS_FAILED + 1))
        fi
    else
        echo -e "${YELLOW}⚠️  runtime.log: 存在しません（初回起動時は正常）${NC}"
    fi
else
    echo -e "${RED}❌ ログディレクトリ: 存在しません ($LOG_DIR)${NC}"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

echo ""

# ============================================
# ③ バックアップ1回手動実行（sanity check）
# ============================================
echo "【③】バックアップスクリプト確認"
echo "------------------------"

BACKUP_SCRIPT="/opt/libertycall/scripts/create_launch_snapshot.sh"
if [ -f "$BACKUP_SCRIPT" ] && [ -x "$BACKUP_SCRIPT" ]; then
    echo -e "${GREEN}✅ バックアップスクリプト: 存在・実行可能${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    
    # バックアップディレクトリ確認
    BACKUP_DIR="/var/backups/libertycall"
    if [ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR" 2>/dev/null; then
        echo -e "${GREEN}✅ バックアップディレクトリ: 準備完了 ($BACKUP_DIR)${NC}"
        CHECKS_PASSED=$((CHECKS_PASSED + 1))
        
        # バックアップ実行（テスト）
        echo "バックアップスクリプトをテスト実行中..."
        if sudo "$BACKUP_SCRIPT" --rotate 3 > /tmp/backup_test.log 2>&1; then
            echo -e "${GREEN}✅ バックアップスクリプト: 実行成功${NC}"
            CHECKS_PASSED=$((CHECKS_PASSED + 1))
            
            # バックアップファイル確認
            BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)
            if [ "$BACKUP_COUNT" -gt 0 ]; then
                LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -1)
                BACKUP_SIZE=$(du -h "$LATEST_BACKUP" 2>/dev/null | cut -f1)
                echo -e "${GREEN}✅ バックアップファイル: 生成成功 ($BACKUP_COUNT ファイル、最新: $(basename "$LATEST_BACKUP"), サイズ: $BACKUP_SIZE)${NC}"
                CHECKS_PASSED=$((CHECKS_PASSED + 1))
            else
                echo -e "${YELLOW}⚠️  バックアップファイル: 見つかりませんでした${NC}"
            fi
        else
            echo -e "${RED}❌ バックアップスクリプト: 実行失敗${NC}"
            echo "   ログ: /tmp/backup_test.log"
            CHECKS_FAILED=$((CHECKS_FAILED + 1))
        fi
    else
        echo -e "${RED}❌ バックアップディレクトリ: 作成失敗 ($BACKUP_DIR)${NC}"
        CHECKS_FAILED=$((CHECKS_FAILED + 1))
    fi
else
    echo -e "${RED}❌ バックアップスクリプト: 存在しないか実行不可 ($BACKUP_SCRIPT)${NC}"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

# cron設定確認
if [ -f "/etc/cron.d/libertycall-daily" ]; then
    echo -e "${GREEN}✅ cron設定: 存在 (/etc/cron.d/libertycall-daily)${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
else
    echo -e "${YELLOW}⚠️  cron設定: 存在しません (/etc/cron.d/libertycall-daily)${NC}"
fi

echo ""

# ============================================
# 結果サマリー
# ============================================
echo "========================================="
echo "確認結果サマリー"
echo "========================================="
echo -e "${GREEN}✅ 成功: $CHECKS_PASSED 項目${NC}"
if [ "$CHECKS_FAILED" -gt 0 ]; then
    echo -e "${RED}❌ 失敗: $CHECKS_FAILED 項目${NC}"
    echo ""
    echo "⚠️  失敗項目がある場合は、上記のエラーメッセージを確認してください。"
    exit 1
else
    echo -e "${GREEN}✅ すべてのチェックが成功しました！${NC}"
    echo ""
    echo "🚀 ローンチ準備完了です。"
    exit 0
fi

