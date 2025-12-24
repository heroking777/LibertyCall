-- LibertyCall: play_audio_sequence Luaスクリプト
-- 同一チャンネル内で全アクションを実行（transferによる別チャンネル化を防止）

-- UUID取得
local uuid = session:getVariable("uuid")
local client_id = session:getVariable("client_id") or "000"

-- ログ出力
freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence start uuid=%s client_id=%s\n", uuid, client_id))

-- 応答
session:answer()

-- A-legのセッションタイムアウトを完全に無効化
session:setVariable("disable-timer", "true")
session:setVariable("media_timeout", "0")
session:setVariable("session_timeout", "0")
-- B-leg終了のA-leg伝搬を防止
session:setVariable("hangup_after_bridge", "false")
session:setVariable("bypass_media_after_bridge", "true")
session:setVariable("disable_b_leg_hangup_propagation", "true")

-- メディア確立を確実に待つ
session:sleep(1500)

-- メディア確立後に録音を非同期で開始
session:execute("set", "execute_on_answer=uuid_record " .. uuid .. " start /tmp/test_call_" .. uuid .. ".wav")

-- 録音開始を確実にするため少し待機
session:sleep(500)

-- 応答速度最適化: RTP処理を最適化してレイテンシ削減
session:setVariable("rtp-autoflush-during-bridge", "false")
session:setVariable("rtp-rewrite-timestamps", "false")
session:setVariable("rtp-autoflush", "false")
session:setVariable("disable-transcoding", "true")

-- セッション録音開始（u-law 8kHz）
local session_client_id = client_id
local record_session_path = string.format("/var/lib/libertycall/sessions/%s/%s/session_%s/audio/caller.wav",
    os.date("%Y-%m-%d"),
    session_client_id,
    os.date("%Y%m%d_%H%M%S")
)
session:execute("set", "record_session=" .. record_session_path)
session:execute("record_session", record_session_path)

-- 必ず再生するアナウンス（無音削減: silence_threshold=0.1でテンプレート間の無音を削減）
session:setVariable("silence_threshold", "0.1")
session:execute("playback", "/opt/libertycall/clients/000/audio/000_8k.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/001_8k.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/002_8k.wav")

-- 録音ファイルが生成されるまで少し待機（2秒）
session:sleep(2000)

-- GatewayへリアルタイムRTPをミラー送信（uuid_rtp_stream使用）
-- 現在の通話UUIDを取得（既に取得済み）
freeswitch.consoleLog("INFO", "[RTP] Starting RTP mirror for call " .. uuid .. "\n")
api = freeswitch.API()
local rtp_result = api:execute("uuid_rtp_stream", uuid .. " start 127.0.0.1:7002 codec=PCMU")
freeswitch.consoleLog("INFO", "[RTP] uuid_rtp_stream result: " .. (rtp_result or "nil") .. "\n")

-- 通話維持（ASR反応待ち）
-- Dialplan途中終了防止：execute_on_media実行後もセッションを維持
session:setVariable("ignore_early_hangup", "true")
session:setVariable("hangup_after_execute", "false")
session:setVariable("continue_on_fail", "true")
session:setVariable("api_hangup_hook", "none")
session:setVariable("ignore_display_updates", "true")
session:setVariable("park_timeout", "0")

-- parkで通話維持
session:execute("park")

freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence end uuid=%s\n", uuid))

