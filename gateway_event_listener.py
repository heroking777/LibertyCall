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
    logger.info("受信イベント: CHANNEL_CREATE, CHANNEL_ANSWER, CHANNEL_EXECUTE_COMPLETE, CHANNEL_HANGUP")
    
    # 受け取るイベントを購読
    # CHANNEL_EXECUTE_COMPLETE: RTPネゴシエーションが完了した時点で発火（RTPポート確定済み）
    con.events("plain", "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_EXECUTE_COMPLETE CHANNEL_HANGUP")
    
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
                    # CHANNEL_ANSWER時点ではRTPポートがまだ確定していないため、
                    # ここではログのみ記録（handle_callはCHANNEL_EXECUTE_COMPLETEで実行）
                    # handle_call(uuid, e)  # コメントアウト：重複起動を防ぐ
                elif event_name == "CHANNEL_EXECUTE_COMPLETE":
                    logger.info(f"実行完了: EXECUTE_COMPLETE イベント UUID={uuid}")
                    # RTPネゴシエーションが完了した時点で確実にポートを取得できる
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


def get_rtp_port(uuid):
    """FreeSWITCHから確実にRTPポートを取得（リトライ機能付き）"""
    import subprocess
    import time
    import re
    
    # CHANNEL_EXECUTE_COMPLETE時点ではRTPネゴシエーションが完了しているため、
    # 短い待機時間で十分（念のため0.5秒待機）
    time.sleep(0.5)
    
    for i in range(5):  # 最大5回リトライ
        try:
            result = subprocess.run(
                ["fs_cli", "-H", "127.0.0.1", "-P", "8021", "-p", "ClueCon", "-x", f"uuid_media {uuid}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3
            )
            
            if result.returncode == 0 and result.stdout:
                logger.debug(f"[get_rtp_port] uuid_media 出力(試行{i+1}):\n{result.stdout.strip()}")
                
                # local_media_portを抽出
                for line in result.stdout.splitlines():
                    line_lower = line.lower()
                    # 形式1: local_media_port=7002
                    if "local_media_port" in line_lower and "=" in line:
                        port = line.split("=")[-1].strip()
                        if port.isdigit():
                            logger.info(f"[get_rtp_port] RTPポート検出成功: {port} (試行{i+1})")
                            return port
                    # 形式2: RTP Local Port: 7002
                    elif "rtp" in line_lower and "local" in line_lower and "port" in line_lower:
                        if ":" in line:
                            port = line.split(":")[-1].strip()
                            if port.isdigit():
                                logger.info(f"[get_rtp_port] RTPポート検出成功: {port} (試行{i+1})")
                                return port
                        else:
                            # 数字だけを抽出
                            match = re.search(r'\d+', line)
                            if match:
                                port = match.group()
                                logger.info(f"[get_rtp_port] RTPポート検出成功: {port} (試行{i+1})")
                                return port
            else:
                logger.debug(f"[get_rtp_port] uuid_media コマンドが失敗しました (試行{i+1}): {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning(f"[get_rtp_port] uuid_media タイムアウト (試行{i+1})")
        except Exception as e:
            logger.warning(f"[get_rtp_port] エラー (試行{i+1}): {e}")
        
        if i < 4:  # 最後の試行でない場合は待機
            time.sleep(1)  # 1秒待って再試行
    
    logger.warning("[get_rtp_port] uuid_media 取得失敗、デフォルト7002使用")
    return "7002"


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
    
    # RTPポートをFreeSWITCHから取得（リトライ機能付き）
    # get_rtp_port()内で1.5秒待機するため、ここでは待機不要
    rtp_port = get_rtp_port(uuid)
    logger.info(f"[handle_call] 使用するRTPポート: {rtp_port}")
    
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

