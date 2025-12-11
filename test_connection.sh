#!/bin/bash
echo "=== LibertyCall 接続診断 ==="
echo ""
echo "1. Viteサーバーの状態:"
ps aux | grep -E "vite|node.*5173" | grep -v grep || echo "  ❌ Viteサーバーが起動していません"

echo ""
echo "2. ポートリスニング状態:"
netstat -tlnp 2>/dev/null | grep 5173 || ss -tlnp | grep 5173 || echo "  ❌ ポート5173でリッスンしていません"

echo ""
echo "3. ファイアウォール設定:"
sudo ufw status | grep 5173 || echo "  ❌ ファイアウォールでポート5173が開放されていません"

echo ""
echo "4. ローカル接続テスト:"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173)
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ ローカル接続: OK (HTTP $HTTP_CODE)"
else
    echo "  ❌ ローカル接続: 失敗 (HTTP $HTTP_CODE)"
fi

echo ""
echo "5. IPアドレス接続テスト（サーバー内から）:"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://160.251.170.253:5173)
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ IP接続: OK (HTTP $HTTP_CODE)"
else
    echo "  ❌ IP接続: 失敗 (HTTP $HTTP_CODE)"
fi

echo ""
echo "=== 診断完了 ==="
