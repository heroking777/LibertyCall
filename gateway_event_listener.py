#!/usr/bin/env python3
"""
FreeSWITCH Event Socket Listener (PyESL版)
通話イベントを常時受信して、gateway処理をトリガーする
"""
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from libs.esl.ESL import ESLconnection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def main():
    """Event Socket Listener のメイン処理"""
    # FreeSWITCH Event Socket 接続パラメータ
    host = "127.0.0.1"
    port = "8021"
    password = "ClueCon"
    
    logger.info(f"FreeSWITCH Event Socket に接続中... ({host}:{port})")
    
    # FreeSWITCH に接続
    con = ESLconnection(host, port, password)
    
    if not con.connected():
        logger.error("Event Socket 接続失敗")
        logger.error("確認: sudo netstat -tulnp | grep 8021")
        logger.error("確認: sudo systemctl status freeswitch")
        return 1
    
    logger.info("Event Socket Listener 起動")
    logger.info("受信イベント: CHANNEL_CREATE, CHANNEL_ANSWER, CHANNEL_HANGUP")
    
    # 受け取るイベントを購読
    con.events("plain", "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_HANGUP")
    
    try:
        while True:
            try:
                e = con.recvEvent()
                if e is None:
                    continue
                
                event_name = e.getHeader("Event-Name")
                uuid = e.getHeader("Unique-ID")
                
                # イベント名が取得できない場合はスキップ
                if not event_name:
                    continue
                
                logger.info(f"EVENT: {event_name} UUID={uuid}")
                
                if event_name == "CHANNEL_CREATE":
                    logger.info(f"チャンネル作成: CREATE イベント UUID={uuid}")
                    handle_channel_create(uuid, e)
                elif event_name == "CHANNEL_ANSWER":
                    logger.info(f"通話開始: ANSWER イベント UUID={uuid}")
                    handle_call(uuid, e)
                elif event_name == "CHANNEL_HANGUP":
                    logger.info(f"通話終了: HANGUP イベント UUID={uuid}")
                    handle_hangup(uuid, e)
            except Exception as e:
                # 個別のイベント処理エラーをログに記録して続行
                logger.warning(f"イベント処理エラー（継続）: {e}")
                continue
    
    except KeyboardInterrupt:
        logger.info("Event Socket Listener を終了します")
        return 0
    except Exception as e:
        logger.error(f"予期しないエラー: {e}", exc_info=True)
        return 1
    finally:
        con.disconnect()
        logger.info("Event Socket 接続を切断しました")


def handle_channel_create(uuid, event):
    """チャンネル作成時の処理"""
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")


def handle_call(uuid, event):
    """通話開始時の処理をここに書きます"""
    import subprocess
    import os
    import time
    
    logger.info(f"[handle_call] 通話処理を開始します UUID={uuid}")
    
    # 通話情報を取得
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")
    
    # RTPポートをFreeSWITCHから取得（少し待ってから取得）
    time.sleep(0.5)  # RTPネゴシエーションが完了するまで少し待つ
    
    rtp_port = "7002"  # デフォルトポート
    try:
        cmd = ["fs_cli", "-H", "127.0.0.1", "-P", "8021", "-p", "ClueCon", "-x", f"uuid_media {uuid}"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        
        if result.returncode == 0:
            logger.info(f"[handle_call] uuid_media 出力:\n{result.stdout}")
            
            # local_media_portを抽出
            for line in result.stdout.splitlines():
                if "local_media_port" in line.lower() or "RTP Local Port" in line:
                    # 形式1: local_media_port=7002
                    if "=" in line:
                        rtp_port = line.split("=")[-1].strip()
                    # 形式2: RTP Local Port: 7002
                    elif ":" in line:
                        rtp_port = line.split(":")[-1].strip()
                    else:
                        # 数字だけを抽出
                        import re
                        match = re.search(r'\d+', line)
                        if match:
                            rtp_port = match.group()
                    break
        else:
            logger.warning(f"[handle_call] uuid_media コマンドが失敗しました: {result.stderr}")
            logger.info(f"[handle_call] デフォルトRTPポートを使用: {rtp_port}")
    except subprocess.TimeoutExpired:
        logger.warning(f"[handle_call] uuid_media コマンドがタイムアウトしました")
        logger.info(f"[handle_call] デフォルトRTPポートを使用: {rtp_port}")
    except Exception as e:
        logger.warning(f"[handle_call] RTPポート取得中にエラー: {e}")
        logger.info(f"[handle_call] デフォルトRTPポートを使用: {rtp_port}")
    
    logger.info(f"[handle_call] RTPポートを検出: {rtp_port}")
    
    # gateway スクリプトのパス
    gateway_script = "/opt/libertycall/libertycall/gateway/realtime_gateway.py"
    
    # パスが存在しない場合は別のパスを試す
    if not os.path.exists(gateway_script):
        gateway_script = "/opt/libertycall/gateway/realtime_gateway.py"
    
    if not os.path.exists(gateway_script):
        logger.error(f"[handle_call] gateway スクリプトが見つかりません: {gateway_script}")
        return
    
    # 通話ごとに独立したプロセスで起動
    try:
        log_file = f"/tmp/gateway_{uuid}.log"
        with open(log_file, "w") as log_fd:
            subprocess.Popen(
                ["python3", gateway_script, "--uuid", uuid, "--rtp_port", rtp_port],
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd="/opt/libertycall"
            )
        logger.info(f"[handle_call] realtime_gateway を起動しました (UUID={uuid}, RTP_PORT={rtp_port})")
        logger.info(f"[handle_call] ログファイル: {log_file}")
    except Exception as e:
        logger.error(f"[handle_call] gateway 起動中にエラー: {e}", exc_info=True)


def handle_hangup(uuid, event):
    """通話終了時の処理"""
    hangup_cause = event.getHeader("Hangup-Cause") or "unknown"
    duration = event.getHeader("variable_duration") or "0"
    logger.info(f"  終了理由: {hangup_cause}, 通話時間: {duration}秒")


if __name__ == "__main__":
    sys.exit(main())

