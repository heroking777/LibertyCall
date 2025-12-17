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
    # 例: realtime_gateway の処理を呼び出す
    logger.info(f"handle_call 実行 UUID={uuid}")
    
    # 通話情報を取得
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")
    
    # TODO: realtime_gateway の処理を呼び出す
    # import realtime_gateway
    # realtime_gateway.process_call(uuid)
    # などの実装


def handle_hangup(uuid, event):
    """通話終了時の処理"""
    hangup_cause = event.getHeader("Hangup-Cause") or "unknown"
    duration = event.getHeader("variable_duration") or "0"
    logger.info(f"  終了理由: {hangup_cause}, 通話時間: {duration}秒")


if __name__ == "__main__":
    sys.exit(main())

