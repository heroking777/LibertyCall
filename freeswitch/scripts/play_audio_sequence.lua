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
    -- RTPを継続的に送信してセッション維持（start_dtmf_generateは削除）
    -- session:execute("start_dtmf_generate")
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

-- GatewayへリアルタイムRTPをミラー送信（UDP経由で127.0.0.1:7002に送信）
-- execute_on_mediaを使用して、メディア確立時にRTPをGatewayに送信
freeswitch.consoleLog("INFO", "[RTP] Setting up RTP mirror to Gateway (127.0.0.1:7002)\n")
session:execute("set", "execute_on_media=record_session udp://127.0.0.1:7002")

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
session:execute("playback", "/opt/libertycall/clients/000/audio/000.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/001.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/002.wav")

-- 録音ファイルが生成されるまで少し待機（2秒）
session:sleep(2000)

-- ========================================
-- 無音監視と催促制御（Lua側で完結）
-- ========================================

-- ASR反応フラグファイルパス
local asr_response_flag_file = string.format("/tmp/asr_response_%s.flag", uuid)

-- 催促音声ファイル
local reminders = {
    "/opt/libertycall/clients/000/audio/prompt_001_8k.wav",
    "/opt/libertycall/clients/000/audio/prompt_002_8k.wav",
    "/opt/libertycall/clients/000/audio/prompt_003_8k.wav"
}

-- タイムアウト設定（秒）
local silence_timeout = 10

-- 初回アナウンス再生後、ASR反応をチェック開始
freeswitch.consoleLog("INFO", "[CALLFLOW] Starting ASR response monitoring after initial prompts\n")

-- ==========================================
-- 無音監視ループ: 10秒ごとにASR反応をチェックし、反応がなければ催促再生
-- ==========================================
freeswitch.consoleLog("INFO", "[CALLFLOW] Entering ASR response monitor loop\n")
local elapsed = 0
local prompt_count = 0
local asr_response_detected = false

while session:ready() and not asr_response_detected and prompt_count < 3 do
    -- 無音を防ぐため、無音ファイルを再生（RTPを流し続ける）
    session:execute("playback", "silence_stream://100")
    freeswitch.msleep(900)
    -- RTPを継続的に送信してセッション維持（start_dtmf_generateは削除）
    -- session:execute("start_dtmf_generate")
    elapsed = elapsed + 1
    
    -- デバッグログ: ループ条件の各要素をチェック（本番用にコメントアウト）
    -- freeswitch.consoleLog("INFO", string.format(
    --     "[CALLFLOW] DEBUG Loop check: ready=%s, asr_detected=%s, prompt_count=%d, elapsed=%d\n",
    --     tostring(session:ready()), tostring(asr_response_detected), prompt_count, elapsed
    -- ))
    
    -- ASR反応フラグファイルをチェック
    local flag_file = io.open(asr_response_flag_file, "r")
    if flag_file then
        io.close(flag_file)
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] ASR response detected! Flag file exists: %s\n", asr_response_flag_file))
        asr_response_detected = true
        break
    end
    
    if elapsed % 5 == 0 then
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] DEBUG Loop iteration=%d, elapsed=%d, session_ready=%s, prompt_count=%d\n",
            elapsed, elapsed, tostring(session:ready()), prompt_count))
    end

    -- 10秒経過したら催促アナウンスを再生
    if elapsed >= 10 then
        prompt_count = prompt_count + 1
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] Timeout %d seconds, playing reminder %d\n", elapsed, prompt_count))
        
        -- 催促アナウンスを再生
        if prompt_count <= #reminders then
            local reminder_path = reminders[prompt_count]
            
            local f = io.open(reminder_path, "r")
            if f then
                io.close(f)
                freeswitch.consoleLog("INFO", "[CALLFLOW] Attempting reminder playback: " .. reminder_path .. "\n")

                -- uuid_displaceではなく、playbackで再生（silence_streamと干渉しないように）
                session:execute("playback", reminder_path)
                freeswitch.consoleLog("INFO", string.format("[CALLFLOW] Played reminder: %s\n", reminder_path))
            else
                freeswitch.consoleLog("ERR", "[CALLFLOW] Reminder file missing: " .. reminder_path .. "\n")
            end
        end
        
        -- 経過時間をリセット（次の10秒カウントを開始）
        elapsed = 0
    end
end

-- ASR反応が検出された場合、または3回の催促後も反応がなかった場合の処理
if asr_response_detected then
    freeswitch.consoleLog("INFO", "[CALLFLOW] ASR response detected, continuing call flow\n")
    -- ASR反応が検出された場合は切断せず、通常の通話フローを継続
elseif prompt_count >= 3 then
    freeswitch.consoleLog("INFO", "[CALLFLOW] No response after 3 reminders, hanging up.\n")
    -- 3回の催促後も反応がなければ切断
    if session:ready() then
        session:hangup("NORMAL_CLEARING")
    end
end

freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence end uuid=%s\n", uuid))


