#!/usr/bin/env python3
"""
Event Socket Listener - 通話ハンドラ群
"""
import os
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

def handle_channel_create(uuid, event):
    """チャンネル作成時の処理"""
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")


def get_rtp_port(uuid):
    """FreeSWITCH Inbound call 用 RTPポート取得（PyESL接続を再利用）
    
    remote_media_port: FreeSWITCHが送信するポート（gatewayが受信するポート）
    """
    logger.info(f"[get_rtp_port] UUID={uuid} のRTPポートを取得中...")
    
    # PyESL接続を取得（メインのイベントリスナー接続を再利用）
    from evl_esl_state import get_esl_connection
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
    """着信処理"""
    logger.info(f"[handle_call] 通話処理を開始します UUID={uuid}")
    
    # デバッグ：音声受信ログ
    with open("/tmp/event_listener.trace", "a") as f:
        f.write(f"[DEBUG_HANDLE_CALL] UUID={uuid} called at {int(time.time())}\n")
    
    # イベント種別を確認
    event_name = event.getHeader("Event-Name")
    application = event.getHeader("Application")
    application_data = event.getHeader("Application-Data") or "-"
    logger.info(
        "[EVL_HANDLE_ENTER] uuid=%s name=%s app=%s data=%s",
        uuid,
        event_name,
        application,
        application_data[:200],
    )

    decision_meta = {"event": event_name, "application": application}
    do_play = False

    # CHANNEL_EXECUTE (playback開始) イベントで呼び出される（この時点でRTP確立済み、チャンネルが生きている）
    if event_name == "CHANNEL_EXECUTE" and application == "playback":
        logger.info(
            f"[handle_call] CHANNEL_EXECUTE (playback開始) イベント検出 → 通話処理開始（RTP確立済み、チャンネル生存中）"
        )
        do_play = True
        decision_meta["trigger"] = "channel_execute"
        rtp_uuid = uuid  # playback開始時点ではUUIDは変わらない、チャンネルが生きている
    elif event_name == "CHANNEL_PARK":
        logger.info(f"[handle_call] CHANNEL_PARK イベント検出 → 通話処理開始（RTP確立済み）")
        # CHANNEL_PARKイベントでは、UUIDが既に新しいUUID（parking bridge上のチャネル）になっている
        rtp_uuid = uuid  # このUUIDが実際のRTPチャネルUUID
        original_uuid = event.getHeader("Original-UUID") or event.getHeader("Channel-Call-UUID") or event.getHeader("Channel-UUID")
        if original_uuid and original_uuid != uuid:
            logger.info(f"[handle_call] park完了: 元のUUID={original_uuid} → 実際のRTPチャネルUUID={rtp_uuid}")
            decision_meta["original_uuid"] = original_uuid
        do_play = True
        decision_meta["trigger"] = "channel_park"
    elif event_name == "CHANNEL_EXECUTE_COMPLETE" and application == "playback":
        # playback完了時はチャンネルが終了している可能性があるため、非推奨
        logger.warning(f"[handle_call] CHANNEL_EXECUTE_COMPLETE (playback完了) で処理（CHANNEL_EXECUTE推奨） UUID={uuid}")
        rtp_uuid = uuid  # playbackではUUIDは変わらないが、チャンネルが終了している可能性あり
        do_play = True
        decision_meta["trigger"] = "execute_complete_playback"
    elif event_name == "CHANNEL_EXECUTE_COMPLETE" and application == "park":
        logger.warning(f"[handle_call] CHANNEL_EXECUTE_COMPLETE (park) で処理（CHANNEL_PARK推奨） UUID={uuid}")
        rtp_uuid = uuid
        do_play = False
        decision_meta["reason"] = "execute_complete_park"
    else:
        logger.info(f"[handle_call] {event_name} (Application={application}) イベントでは処理をスキップします")
        decision_meta["reason"] = "unsupported_event"

    if not do_play:
        from evl_helpers import _log_play_decide
        _log_play_decide(uuid, False, **decision_meta)
        return

    from evl_helpers import _log_play_decide
    _log_play_decide(uuid, True, **decision_meta)
    
    # 通話情報を取得
    caller_id = event.getHeader("Caller-Caller-ID-Number") or "unknown"
    destination = event.getHeader("Caller-Destination-Number") or "unknown"
    logger.info(f"  Caller: {caller_id} -> Destination: {destination}")

    # uuid_exists確認
    from evl_esl_state import get_esl_connection
    esl_conn = get_esl_connection()
    if esl_conn:
        try:
            exists_resp = esl_conn.api("uuid_exists", uuid)
            exists_str = str(exists_resp).strip().splitlines()[0] if exists_resp else ""
            logger.info("[EVL_ESL_UUID_CHECK] uuid=%s resp=%s", uuid, exists_str)
        except Exception as exc:
            logger.exception("[EVL_ESL_UUID_CHECK] uuid=%s err=%s", uuid, exc)
    else:
        logger.warning("[EVL_ESL_UUID_CHECK] uuid=%s resp=NO_CONN", uuid)
    
    # park完了後にRTPメディア確立を待つ（FreeSWITCHが内部でRTPバインドを完了するまで待機）
    logger.info(f"[handle_call] park完了 → RTP確立待機中 (1.0秒)")
    time.sleep(1.0)
    
    # execute_on_mediaで固定ポート7002にRTP転送するため、固定ポートを使用
    # FreeSWITCHがsocket:127.0.0.1:7002にRTPを転送するため、Gatewayも7002で待機
    rtp_port = "7002"
    logger.info(f"[handle_call] execute_on_media使用のため、固定ポート7002を使用")
    
    # gateway スクリプトのパス
    gateway_script = "/opt/libertycall/libertycall/gateway/realtime_gateway.py"
    
    # パスが存在しない場合は別のパスを試す
    if not os.path.exists(gateway_script):
        gateway_script = "/opt/libertycall/gateway/realtime_gateway.py"
    
    if not os.path.exists(gateway_script):
        logger.error(f"[handle_call] gateway スクリプトが見つかりません: {gateway_script}")
        from evl_helpers import _log_play_decide
        _log_play_decide(uuid, False, reason="gateway_script_missing", script=gateway_script)
        return
    
    # 通話ごとに独立したプロセスで起動
    try:
        log_file = f"/tmp/gateway_{uuid}.log"
        logger.info(f"[handle_call] Preparing to spawn realtime_gateway for uuid={uuid} (log={log_file})")
        # 必要な環境変数のみを選択的に渡す（LC_RTP_PORT等は引数で上書きされるため除外）
        env = {}
        env["PATH"] = "/opt/libertycall/venv/bin:/usr/bin:/usr/local/bin"
        env["PYTHONPATH"] = "/opt/libertycall"
        # ASR関連の環境変数を渡す
        for key in ["LC_ASR_STREAMING_ENABLED", "LC_ASR_PROVIDER", "LC_ASR_CHUNK_MS", "LC_ASR_SILENCE_MS", 
                    "LC_DEFAULT_CLIENT_ID", "LC_TTS_STREAMING", "PYTHONUNBUFFERED",
                    "LIBERTYCALL_CONSOLE_ENABLED", "LIBERTYCALL_CONSOLE_API_BASE_URL", "GOOGLE_APPLICATION_CREDENTIALS"]:
            value = os.getenv(key)
            if value is not None:
                env[key] = value
        # デフォルトでストリーミングを有効化（環境変数が設定されていない場合）
        if "LC_ASR_STREAMING_ENABLED" not in env:
            env["LC_ASR_STREAMING_ENABLED"] = "1"
        with open(log_file, "w") as log_fd:
            logger.info("[LISTENER_DEBUG] About to spawn realtime_gateway")
            cmd = ["python3", gateway_script, "--uuid", uuid, "--rtp_port", rtp_port]
            logger.info(
                "[EVL_ESL_SEND] uuid=%s cmd=%s",
                uuid,
                " ".join(cmd),
            )
            process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd="/opt/libertycall",
                env=env
            )
            logger.info(f"[LISTENER_DEBUG] Gateway process spawned with PID={process.pid}")
            logger.info(
                "[EVL_ESL_RESP] uuid=%s ok=1 pid=%s",
                uuid,
                process.pid,
            )
        logger.info(f"[handle_call] realtime_gateway を起動しました (UUID={uuid}, RTP_PORT={rtp_port})")
        logger.info(f"[handle_call] ログファイル: {log_file}")
    except Exception as e:
        logger.error(f"[handle_call] gateway 起動中にエラー: {e}", exc_info=True)
        logger.exception("[EVL_ESL_RESP] uuid=%s ok=0 err=%s", uuid, e)


def handle_hangup(uuid, event):
    """通話終了時の処理"""
    hangup_cause = event.getHeader("Hangup-Cause") or "unknown"
    duration = event.getHeader("variable_duration") or "0"
    logger.info(f"  終了理由: {hangup_cause}, 通話時間: {duration}秒")
