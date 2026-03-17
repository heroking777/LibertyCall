# LibertyCall AI電話システム - システム概要

## VM情報
- ホスト: vm-10a3a4dd-25
- ディスク: 99GB
- OS: Ubuntu (systemd)

## アーキテクチャ

着信 → 楽天SIP(61.213.230.145) → FreeSWITCH(:5072) → answer + sleep 200ms → uuid_audio_fork → WebSocket(:9000) → ws_sink.py → SilenceHandler: アナウンス再生(ESL経由) → GasrSession: Google Speech-to-Text(ASR) → dialogue_flow.py: パターンマッチ → 転送/お断り/聞き直し → uuid_record: 通話録音


## プロセス構成
| プロセス | ポート | systemd | 説明 |
|---------|--------|---------|------|
| ws_sink.py | 9000(WS), 9002(TCP) | ws-sink.service | ASR WebSocketサーバー、対話管理 |
| gateway_event_listener.py | - | gateway-listener.service | FreeSWITCHイベント監視 |
| console_backend (uvicorn) | 8001 | 手動起動 | 管理画面API (FastAPI) |
| FreeSWITCH | 5060,5072,5080 | freeswitch.service | SIPゲートウェイ |
| ESL | 8021 | (FreeSWITCH内蔵) | Event Socket Library |

## 電話番号
| 番号 | 用途 | dialplan extension |
|------|------|-------------------|
| 05058304073 (000) | メイン本番 | af_fork_58304073 |
| 05058654181 (001) | サブ番号 | af_fork_58304073 / inbound_001 |
| 05055271174 | ウィスパーテスト | inbound_whisper |
| 05058465301 | デリテスト | af_fork_deli |
| 05058650640 | via用 | - |

## 主要ファイルパス
- ASRコア: /opt/libertycall/asr_stream/
  - ws_sink.py: WebSocketサーバー(メインプロセス)
  - gasr_session.py: Google ASRセッション管理
  - silence_handler.py: アナウンス再生・沈黙検知
  - call_logger.py: 通話ログ(SQLite)
  - raw_server.py: TCPサーバー(:9002)
- 対話ロジック: /opt/libertycall/gateway/dialogue/dialogue_flow.py
- クライアント設定: /opt/libertycall/clients/000/config/dialogue_config.json
- 音声ファイル: /opt/libertycall/clients/000/audio/
- DB: /opt/call_console.db
- 録音: /opt/libertycall/recordings/
- ログ: /tmp/ws_sink_debug.log (RotatingFile 5MB x3)
- dialplan: /usr/local/freeswitch/conf/dialplan/public_minimal.xml
- SIPプロファイル: /usr/local/freeswitch/conf/sip_profiles/lab_open/rakuten.xml

## ESL接続
- ホスト: 127.0.0.1:8021 パスワード: ClueCon
- 環境変数: AF_ESL_HOST, AF_ESL_PORT, AF_ESL_PASSWORD
- 3箇所で独立接続: ws_sink(共有), gasr_session(個別), silence_handler(個別)
- ws_sinkの_ensure_esl()でstale接続を事前検出

## 通話フロー
1. 着信 → FreeSWITCH answer → sleep 200ms → uuid_audio_fork
2. ws_sink: WebSocket接続受信
3. SilenceHandler作成 → 即座にplay_greeting_only(000.wav再生)
4. 並行: caller_number取得 + uuid_record + GasrSession初期化
5. greeting完了 → unmute → ASR開始 → silence timer開始
6. 音声認識 → dialogue_flow.pyでパターンマッチ
7. 結果に応じて: 転送(081) / お断り(094) / 聞き直し(114) / 終話(086+087)

## 対話フロー設計
- パターンマッチ: dialogue_config.jsonのpatternsを順番チェック
- retry_limit=1: マッチせず1回→聞き直し、2回→転送確認
- transfer_confirm: 「はい」→転送、「いいえ」→終話、2回不明→強制転送
- sales_check: 営業キーワード→確認→お断り
- partner_call: 取引先キーワード→転送確認(sales_checkより優先)
- configキャッシュ: mtimeチェックで自動リロード

## SIPセキュリティ
- iptables: 楽天IP(61.213.230.145)のみACCEPT、他は全DROP
- 対象ポート: 5060, 5072, 5080 (tcp/udp)
- localhost(:5060)もACCEPT(FreeSWITCH内部通信用)

## 運用
- DBバックアップ: /opt/libertycall/backup_db.sh (cron毎日3時、7日保持)
- ヘルスチェック: /opt/libertycall/monitor_health.sh (cron毎分)
- ログローテーション: /tmp/ws_sink_debug.log (5MB x 3世代)
- dialplanバックアップ: backup_db.shでdialogue_configも含む

## トラブルシューティング
- ws_sink再起動: sudo systemctl restart ws-sink
- FreeSWITCH dialplanリロード: /usr/local/freeswitch/bin/fs_cli -x "reloadxml"
- SIP gateway確認: /usr/local/freeswitch/bin/fs_cli -x "sofia status"
- 通話ログ確認: grep "AF_WS\|ESL\|GREETING\|play_audio" /tmp/ws_sink_debug.log | tail -30
- ESL接続テスト: /usr/local/freeswitch/bin/fs_cli -x "status"
