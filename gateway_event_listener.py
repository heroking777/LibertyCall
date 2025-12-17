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
    
    # 重複起動を防ぐためのUUID管理
    active_calls = set()
    
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
                    # 重複起動を防ぐ（同じUUIDで既に処理中でないか確認）
                    if uuid not in active_calls:
                        active_calls.add(uuid)
                        # RTPネゴシエーションが完了した時点で確実にポートを取得できる
                        handle_call(uuid, e)
                    else:
                        logger.debug(f"[重複防止] UUID={uuid} は既に処理中です")
                elif event_name == "CHANNEL_HANGUP":
                    logger.info(f"通話終了: HANGUP イベント UUID={uuid}")
                    # 処理完了したUUIDを削除
                    active_calls.discard(uuid)
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
    """FreeSWITCH Inbound call 用 RTPポート取得（Event Socket Protocolを直接使用）"""
    import socket
    import time
    
    logger.info(f"[get_rtp_port] UUID={uuid} のRTPポートを取得中...")
    
    # Event Socket Protocolを直接使用（fs_cliを経由しない）
    host = "127.0.0.1"
    port = 8021
    password = "ClueCon"
    
    # 最大5回リトライ（RTP確立を待つ）
    for i in range(5):
        try:
            # RTP確立待機（各リトライ前に1.5秒待機）
            time.sleep(1.5)
            
            logger.debug(f"[get_rtp_port] Event Socket接続試行(試行{i+1}): {host}:{port}")
            
            # TCP接続
            sock = socket.create_connection((host, port), timeout=5)
            
            try:
                # 認証リクエストを受信
                auth_request = sock.recv(1024).decode('utf-8', errors='ignore')
                logger.debug(f"[get_rtp_port] 認証リクエスト受信: {auth_request[:50]}")
                
                # 認証送信
                auth_cmd = f"auth {password}\n\n"
                sock.sendall(auth_cmd.encode('utf-8'))
                
                # 認証応答を受信
                auth_response = sock.recv(1024).decode('utf-8', errors='ignore')
                logger.debug(f"[get_rtp_port] 認証応答: {auth_response[:50]}")
                
                if "OK" not in auth_response and "accepted" not in auth_response.lower():
                    logger.warning(f"[get_rtp_port] 認証失敗 (試行{i+1}): {auth_response[:100]}")
                    sock.close()
                    continue
                
                # uuid_getvarコマンドを送信
                api_cmd = f"api uuid_getvar {uuid} local_media_port\n\n"
                sock.sendall(api_cmd.encode('utf-8'))
                
                # 応答を受信
                response = b""
                while True:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    response += chunk
                    # Content-Lengthを確認して完全な応答を受信
                    if b"Content-Length:" in response:
                        # Content-Lengthの値を取得
                        lines = response.decode('utf-8', errors='ignore').split('\n')
                        content_length = 0
                        for line in lines:
                            if line.startswith("Content-Length:"):
                                try:
                                    content_length = int(line.split(":")[1].strip())
                                    break
                                except (ValueError, IndexError):
                                    pass
                        
                        if content_length > 0:
                            # ヘッダー部分とボディ部分を分離
                            header_end = response.find(b"\n\n")
                            if header_end != -1:
                                body_start = header_end + 2
                                body = response[body_start:]
                                if len(body) >= content_length:
                                    # 完全な応答を受信
                                    break
                
                response_text = response.decode('utf-8', errors='ignore')
                logger.debug(f"[get_rtp_port] 応答(試行{i+1}): {response_text[:200]}")
                
                # ボディ部分を抽出
                body_start = response_text.find("\n\n")
                if body_start != -1:
                    body = response_text[body_start + 2:].strip()
                    # 数字かどうかをチェック（成功時）
                    if body.isdigit():
                        logger.info(f"[get_rtp_port] local_media_port={body} (試行{i+1})")
                        sock.close()
                        return body
                    elif "-ERR" in body:
                        logger.warning(f"[get_rtp_port] FreeSWITCH応答エラー: {body} (試行{i+1})")
                    else:
                        logger.debug(f"[get_rtp_port] 出力(試行{i+1}): {body}")
                
                sock.close()
                
            except Exception as e:
                sock.close()
                raise e
        
        except socket.timeout:
            logger.warning(f"[get_rtp_port] Event Socket接続タイムアウト (試行{i+1})")
        except socket.error as e:
            logger.warning(f"[get_rtp_port] Event Socket接続エラー (試行{i+1}): {e}")
        except Exception as e:
            logger.warning(f"[get_rtp_port] エラー (試行{i+1}): {e}", exc_info=True)
    
    logger.warning("[get_rtp_port] 全試行失敗、デフォルト7002使用")
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

