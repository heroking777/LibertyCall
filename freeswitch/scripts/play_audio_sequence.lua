-- LibertyCall: play_audio_sequence Luaスクリプト
-- 同一チャンネル内で全アクションを実行（transferによる別チャンネル化を防止）

-- UUID取得
local uuid = session:getVariable("uuid")
local client_id = session:getVariable("client_id") or "000"
-- UUIDを変数に保存（Zombieセッションでも失わないように、グローバル変数として定義）
local call_uuid = nil

-- ログ出力
freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence start uuid=%s client_id=%s\n", uuid, client_id))

-- ========================================
-- セッション初期化と通話安定化
-- ========================================

if not session:ready() then
    freeswitch.consoleLog("WARNING", "[CALLFLOW] Session not ready, waiting 500ms...\n")
    freeswitch.msleep(500)
end

-- 確実に応答状態にする（これが無いとplaybackで即切断する）
-- 通話が確実に確立するまで待つ（最大3秒）
if not session:answered() then
    freeswitch.consoleLog("INFO", "[CALLFLOW] Answering call to enable audio playback\n")
    session:answer()
    -- UUIDを変数に保存（Zombieセッションでも失わないように）
    call_uuid = session:get_uuid()
    freeswitch.consoleLog("INFO", "[CALLFLOW] Stored call UUID: " .. tostring(call_uuid) .. "\n")
    -- RTPを継続的に送信してセッション維持
    session:execute("start_dtmf_generate")
    local wait_start = os.time()
    while not session:ready() and os.difftime(os.time(), wait_start) < 3 do
        freeswitch.msleep(250)
    end
    freeswitch.consoleLog("INFO", "[CALLFLOW] Call answered and RTP ready\n")
end

-- タイムアウト設定を明示的に設定（SIPプロファイルの設定を確実に適用）
session:setVariable("media_timeout", "60")
session:setVariable("rtp-timeout-sec", "60")
session:setVariable("rtp-hold-timeout-sec", "300")
session:setVariable("rtp-keepalive-ms", "500")
freeswitch.consoleLog("INFO", "[CALLFLOW] Timeout settings applied: media_timeout=60, rtp-timeout-sec=60\n")

-- hangup_after_bridgeをfalseにして勝手に切断されないようにする
session:setVariable("hangup_after_bridge", "false")
session:setVariable("ignore_display_updates", "true")
session:setVariable("playback_terminators", "")

-- AutoHangupを無効化（playback完了時に勝手にhangupするのを防ぐ）
session:setAutoHangup(false)

-- A-legのセッションタイムアウト設定（催促やASR動作のための余裕を確保）
session:setVariable("disable-timer", "true")
session:setVariable("media_timeout", "60")  -- SIPプロファイルの設定と合わせて60秒に設定
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

-- デバッグ用: ffmpegで強制的に音声をUDP送信（uuid_rtp_streamが動作しない場合のテスト）
-- bash -c '... & disown' により確実に非同期実行（FreeSWITCHの同期ブロックを回避）
freeswitch.consoleLog("INFO", "[RTP_DEBUG] Starting ffmpeg test stream to 127.0.0.1:7002\n")
local ffmpeg_path = "/usr/bin/ffmpeg"
local cmd = string.format(
    "bash -c '%s -re -i /opt/libertycall/clients/000/audio/000_8k.wav -ar 8000 -ac 1 -acodec pcm_mulaw -f rtp udp://127.0.0.1:7002 > /tmp/ffmpeg_rtp_test.log 2>&1 & disown'",
    ffmpeg_path
)
freeswitch.consoleLog("INFO", "[RTP_DEBUG] Exec command: " .. cmd .. "\n")
local result = api:execute("system", cmd)
freeswitch.consoleLog("INFO", "[RTP_DEBUG] ffmpeg launch result: " .. (result or "nil") .. "\n")

-- ========================================
-- 無音監視と催促制御（Lua側で完結）
-- ========================================

-- ASR検出タイムスタンプファイル
local asr_timestamp_file = "/tmp/asr_last.txt"

-- 催促音声ファイル
local reminders = {
    "/opt/libertycall/clients/000/audio/000-004_8k.wav",
    "/opt/libertycall/clients/000/audio/000-005_8k.wav",
    "/opt/libertycall/clients/000/audio/000-006_8k.wav"
}

-- タイムアウト設定（秒）
local silence_timeout = 10

-- 初回アナウンス再生後、ASRモニタ開始までの待機時間（10秒）
freeswitch.consoleLog("INFO", "[CALLFLOW] Waiting 10 seconds after initial prompts before starting silence monitoring\n")
session:sleep(10000)

-- ==========================================
-- 無音監視ループ: 10秒ごとに催促再生
-- ==========================================
freeswitch.consoleLog("INFO", "[CALLFLOW] Entering silence monitor loop\n")
local elapsed = 0
local prompt_count = 0

while session:ready() do
    freeswitch.msleep(1000)
    -- RTPを継続的に送信してセッション維持（1秒ごとに再送信を明示）
    session:execute("start_dtmf_generate")
    elapsed = elapsed + 1
    if elapsed % 5 == 0 then
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] DEBUG Loop iteration=%d, elapsed=%d, session_ready=%s\n",
            elapsed, elapsed, tostring(session:ready())))
    end

    if elapsed >= 10 then
        prompt_count = prompt_count + 1
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] Timeout %d, playing reminder %d\n", elapsed, prompt_count))
        local reminder_path = string.format("/opt/libertycall/clients/000/audio/000-00%d_8k.wav", prompt_count + 3)

        local f = io.open(reminder_path, "r")
        if f then
            io.close(f)
            freeswitch.consoleLog("INFO", "[CALLFLOW] Attempting reminder playback: " .. reminder_path .. "\n")

            -- RTP経路を強制的に再確立してから再生
            local api = freeswitch.API()
            local current_uuid = call_uuid or session:get_uuid()

            if current_uuid then
                freeswitch.consoleLog("INFO", "[CALLFLOW] Re-negotiating RTP for UUID: " .. current_uuid .. "\n")
                local reneg = api:executeString("uuid_media_renegotiate " .. current_uuid)
                freeswitch.consoleLog("INFO", "[CALLFLOW] RTP renegotiate result: " .. tostring(reneg) .. "\n")

                -- 100ms待機してから再生ジョブを登録
                freeswitch.msleep(100)
                local cmd = string.format("uuid_broadcast %s playback %s both", current_uuid, reminder_path)
                local sched_cmd = string.format("sched_api +1 none %s", cmd)
                freeswitch.consoleLog("INFO", "[CALLFLOW] Executing sched_api command: " .. sched_cmd .. "\n")

                local ok, result = pcall(function()
                    return api:executeString(sched_cmd)
                end)

                if ok then
                    freeswitch.consoleLog("INFO", "[CALLFLOW] Reminder playback (sched_api) result: " .. tostring(result) .. "\n")
                else
                    freeswitch.consoleLog("ERR", "[CALLFLOW] sched_api execution failed: " .. tostring(result) .. "\n")
                end

                -- 送信後にLuaスレッドを1秒キープして即GCを防止
                freeswitch.msleep(1000)
            else
                freeswitch.consoleLog("ERR", "[CALLFLOW] call_uuid is nil, cannot play reminder\n")
            end

        else
            freeswitch.consoleLog("ERR", "[CALLFLOW] Reminder file missing: " .. reminder_path .. "\n")
        end

        if prompt_count >= 3 then
            freeswitch.consoleLog("INFO", "[CALLFLOW] No response after 3 reminders, hanging up.\n")
            break
        end
        elapsed = 0
    end
end

if session:ready() then
    session:hangup()
end

freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence end uuid=%s\n", uuid))

