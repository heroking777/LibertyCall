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


class FreeSwitchSocketClient:
    """FreeSWITCH Event Socket Protocol 永続接続クライアント"""
    def __init__(self, host="127.0.0.1", port=8021, password="ClueCon"):
        import socket
        self.socket = socket  # socketモジュールを保持
        self.host = host
        self.port = port
        self.password = password
        self.sock = None
        self._lock = None  # スレッドセーフ用（必要に応じて）
    
    def connect(self):
        """Event Socketに接続して認証（既に接続済みの場合は再利用）"""
        if self.sock:
            try:
                # 接続が生きているか確認（簡単なテスト）
                self.sock.settimeout(0.1)
                self.sock.recv(1, self.socket.MSG_PEEK)
                self.sock.settimeout(None)
                return  # 既に接続済み
            except (self.socket.error, OSError):
                # 接続が切れている場合は再接続
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None
        
        # 新規接続
        self.sock = self.socket.create_connection((self.host, self.port), timeout=5)
        
        # バナーを受信
        banner = self.sock.recv(1024).decode('utf-8', errors='ignore')
        logger.debug(f"[FreeSwitchSocketClient] バナー受信: {banner[:50]}")
        
        if "auth/request" in banner:
            # 認証送信
            auth_cmd = f"auth {self.password}\r\n\r\n"
            self.sock.sendall(auth_cmd.encode('utf-8'))
            
            # 認証応答を受信
            reply = self.sock.recv(1024).decode('utf-8', errors='ignore')
            logger.debug(f"[FreeSwitchSocketClient] 認証応答: {reply[:50]}")
            
            if "+OK" not in reply and "accepted" not in reply.lower():
                self.sock.close()
                self.sock = None
                raise Exception(f"認証失敗: {reply[:100]}")
            
            logger.debug("[FreeSwitchSocketClient] 認証成功")
        else:
            logger.warning(f"[FreeSwitchSocketClient] 認証リクエストが見つかりません: {banner[:50]}")
    
    def api(self, cmd):
        """APIコマンドを実行して応答を取得"""
        self.connect()  # 接続確認・必要に応じて再接続
        
        # コマンド送信
        api_cmd = f"api {cmd}\r\n\r\n"
        self.sock.sendall(api_cmd.encode('utf-8'))
        
        # 応答を受信
        response = b""
        while True:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            response += chunk
            # Content-Lengthを確認して完全な応答を受信
            if b"Content-Length:" in response:
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
                    header_end = response.find(b"\n\n")
                    if header_end != -1:
                        body_start = header_end + 2
                        body = response[body_start:]
                        if len(body) >= content_length:
                            break
        
        response_text = response.decode('utf-8', errors='ignore')
        
        # ボディ部分を抽出
        body_start = response_text.find("\n\n")
        if body_start != -1:
            body = response_text[body_start + 2:].strip()
            return body
        return response_text.strip()
    
    def close(self):
        """接続を閉じる"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


# グローバルなPyESL Event Socket接続（メインのイベントリスナー接続を再利用）
_esl_connection = None

def set_esl_connection(con):
    """PyESL接続をグローバルに設定"""
    global _esl_connection
    _esl_connection = con

def get_esl_connection():
    """PyESL接続を取得"""
    global _esl_connection
    return _esl_connection


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
    
    # グローバルに接続を設定（get_rtp_port()で再利用）
    set_esl_connection(con)
    
    logger.info("Event Socket Listener 起動")
    logger.info("受信イベント: CHANNEL_CREATE, CHANNEL_ANSWER, CHANNEL_EXECUTE_COMPLETE, CHANNEL_PARK, CHANNEL_HANGUP")
    
    # 受け取るイベントを購読
    # CHANNEL_PARK: park完了後、parking bridgeに移動した新しいUUIDを取得（RTP確立済み）
    # CHANNEL_EXECUTE_COMPLETE: park実行完了（RTP確立前の可能性あり）
    con.events("plain", "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_EXECUTE_COMPLETE CHANNEL_PARK CHANNEL_HANGUP")
    
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
                    # CHANNEL_ANSWER時点ではまだRTP未確立のため、ここでは処理しない
                    # 実際の通話処理はCHANNEL_EXECUTE_COMPLETE (park完了) で実行
                elif event_name == "CHANNEL_EXECUTE_COMPLETE":
                    application = e.getHeader("Application")
                    logger.info(f"実行完了: EXECUTE_COMPLETE イベント UUID={uuid}, Application={application}")
                    # park完了時はCHANNEL_PARKイベントで処理するため、ここではスキップ
                    # CHANNEL_PARKイベントの方が確実に新しいUUID（RTP確立済み）を取得できる
                    if application == "park":
                        logger.debug(f"[CHANNEL_EXECUTE_COMPLETE] park完了を検出（CHANNEL_PARK待機中） UUID={uuid}")
                elif event_name == "CHANNEL_PARK":
                    # CHANNEL_PARK: park完了後、parking bridgeに移動した新しいUUIDを取得
                    # この時点でRTPが確立されているため、ここで通話処理を開始
                    new_uuid = e.getHeader("Unique-ID")
                    old_uuid = e.getHeader("Channel-Call-UUID") or e.getHeader("Channel-UUID") or uuid
                    logger.info(f"[CHANNEL_PARK] 通話がparking bridgeに移動: 新UUID={new_uuid}, 元UUID={old_uuid}")
                    # 重複起動を防ぐ（同じUUIDで既に処理中でないか確認）
                    if new_uuid and new_uuid not in active_calls:
                        active_calls.add(new_uuid)
                        # 元のUUIDも記録（gateway起動時に使用）
                        e.addHeader("Original-UUID", old_uuid)
                        handle_call(new_uuid, e)
                    else:
                        logger.debug(f"[重複防止] UUID={new_uuid} は既に処理中です")
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
        # グローバル接続をクリア
        set_esl_connection(None)


def handle_channel_create(uuid, event):
    """チャンネル作成時の処理"""
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")


def get_rtp_port(uuid):
    """FreeSWITCH Inbound call 用 RTPポート取得（PyESL接続を再利用）
    
    remote_media_port: FreeSWITCHが送信するポート（gatewayが受信するポート）
    """
    import time
    
    logger.info(f"[get_rtp_port] UUID={uuid} のRTPポートを取得中...")
    
    # PyESL接続を取得（メインのイベントリスナー接続を再利用）
    con = get_esl_connection()
    if not con or not con.connected():
        logger.warning("[get_rtp_port] PyESL接続が利用できません")
        return "7002"
    
    # 初期待機（RTP確立を待つ）
    time.sleep(1.0)
    
    # 最大5回リトライ（RTP確立を待つ）
    for i in range(5):
        try:
            logger.debug(f"[get_rtp_port] APIコマンド実行(試行{i+1}): uuid_getvar {uuid} remote_media_port")
            
            # PyESLのapi()メソッドを使用（既存の接続を再利用）
            # remote_media_port: FreeSWITCHが送信するポート（gatewayが受信するポート）
            event = con.api("uuid_getvar", f"{uuid} remote_media_port")
            
            if event is None:
                logger.warning(f"[get_rtp_port] API応答がNone (試行{i+1})")
                if i < 4:  # 最後の試行でない場合は待機
                    time.sleep(0.5)
                continue
            
            # 応答ボディを取得
            response = event.getBody()
            if response:
                response = response.strip()
            
            logger.debug(f"[get_rtp_port] 応答(試行{i+1}): {response}")
            
            # 数字かどうかをチェック（成功時）
            if response and response.isdigit():
                logger.info(f"[get_rtp_port] remote_media_port={response} (試行{i+1})")
                return response
            elif response and "-ERR" in response:
                logger.warning(f"[get_rtp_port] FreeSWITCH応答エラー: {response} (試行{i+1})")
                # -ERR No such channel の場合は、まだRTPが確立していない可能性がある
                if "No such channel" in response:
                    if i < 4:  # 最後の試行でない場合は待機
                        time.sleep(0.5)
                    continue  # 次の試行へ
            else:
                logger.debug(f"[get_rtp_port] 出力(試行{i+1}): {response}")
            
            if i < 4:  # 最後の試行でない場合は待機
                time.sleep(0.5)
        
        except Exception as e:
            logger.warning(f"[get_rtp_port] エラー (試行{i+1}): {e}", exc_info=True)
            if i < 4:  # 最後の試行でない場合は待機
                time.sleep(0.5)
    
    logger.warning("[get_rtp_port] 全試行失敗、デフォルト7002使用")
    return "7002"


def handle_call(uuid, event):
    """通話開始時の処理（CHANNEL_PARK イベントで呼び出される）"""
    import subprocess
    import os
    
    logger.info(f"[handle_call] 通話処理を開始します UUID={uuid}")
    
    # イベント種別を確認
    event_name = event.getHeader("Event-Name")
    
    # CHANNEL_PARK イベントで呼び出される（この時点でRTP確立済み）
    if event_name == "CHANNEL_PARK":
        logger.info(f"[handle_call] CHANNEL_PARK イベント検出 → 通話処理開始（RTP確立済み）")
        # CHANNEL_PARKイベントでは、UUIDが既に新しいUUID（parking bridge上のチャネル）になっている
        rtp_uuid = uuid  # このUUIDが実際のRTPチャネルUUID
        original_uuid = event.getHeader("Original-UUID") or event.getHeader("Channel-Call-UUID") or event.getHeader("Channel-UUID")
        if original_uuid and original_uuid != uuid:
            logger.info(f"[handle_call] park完了: 元のUUID={original_uuid} → 実際のRTPチャネルUUID={rtp_uuid}")
    else:
        # フォールバック: CHANNEL_EXECUTE_COMPLETE (park) の場合（非推奨）
        application = event.getHeader("Application")
        if event_name == "CHANNEL_EXECUTE_COMPLETE" and application == "park":
            logger.warning(f"[handle_call] CHANNEL_EXECUTE_COMPLETE (park) で処理（CHANNEL_PARK推奨） UUID={uuid}")
            rtp_uuid = uuid
        else:
            logger.info(f"[handle_call] {event_name} (Application={application}) イベントでは処理をスキップします")
            return
    
    # 通話情報を取得
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")
    
    # park完了後にRTPメディア確立を待つ（FreeSWITCHが内部でRTPバインドを完了するまで待機）
    import time
    logger.info(f"[handle_call] park完了 → RTP確立待機中 (1.0秒)")
    time.sleep(1.0)
    
    # RTPポート取得（再試行ロジック付き、実際のRTPチャネルUUIDを使用）
    rtp_port = None
    for i in range(6):  # 最大6回試行（合計約3秒待機）
        rtp_port = get_rtp_port(rtp_uuid)
        if rtp_port and rtp_port != "7002" and rtp_port.isdigit():
            logger.info(f"[handle_call] RTPポート取得成功: {rtp_port} (試行{i+1})")
            break
        if i < 5:  # 最後の試行でない場合は待機
            logger.debug(f"[handle_call] RTPポート取得失敗、再試行待機中 (0.5秒)...")
            time.sleep(0.5)
    
    if not rtp_port or rtp_port == "7002":
        logger.warning(f"[handle_call] RTPポート取得に失敗、デフォルト7002使用")
        rtp_port = "7002"
    
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
                cwd="/opt/libertycall",
                env={}  # 親環境変数を完全にリセット（LC_RTP_PORT等が引数を上書きしないように）
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