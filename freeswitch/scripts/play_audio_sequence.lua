-- LibertyCall: play_audio_sequence Luaスクリプト
-- 同一チャンネル内で全アクションを実行（transferによる別チャンネル化を防止）

-- UUID取得
local uuid = session:getVariable("uuid")
local client_id = session:getVariable("client_id") or "000"

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
    local wait_start = os.time()
    while not session:ready() and os.difftime(os.time(), wait_start) < 3 do
        freeswitch.msleep(250)
    end
    freeswitch.consoleLog("INFO", "[CALLFLOW] Call answered and RTP ready\n")
end

-- hangup_after_bridgeをfalseにして勝手に切断されないようにする
session:setVariable("hangup_after_bridge", "false")
session:setVariable("ignore_display_updates", "true")
session:setVariable("playback_terminators", "")

-- AutoHangupを無効化（playback完了時に勝手にhangupするのを防ぐ）
session:setAutoHangup(false)

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

-- ==========================================
-- 無音RTPストリームを送信（相手側RTP監視維持）
-- ==========================================
-- silence_stream://-1 は無限に無音RTP payloadを送り続ける
-- これにより、相手側（SIPキャリア）がRTP無通信と判断せず、10秒タイムアウトが発生しない
freeswitch.consoleLog("INFO", "[CALLFLOW] Starting background silence stream (keepalive RTP)\n")
-- uuid_broadcastを使用して別スレッドで無音ストリームを再生（Luaロジックと競合しない）
api = freeswitch.API()
local broadcast_result = api:executeString("uuid_broadcast " .. uuid .. " silence_stream://-1 both")
freeswitch.consoleLog("INFO", "[CALLFLOW] uuid_broadcast result: " .. (broadcast_result or "nil") .. "\n")

-- 初回アナウンス再生後、ASRモニタ開始までの待機時間（10秒）
freeswitch.consoleLog("INFO", "[CALLFLOW] Waiting 10 seconds after initial prompts before starting silence monitoring\n")
session:sleep(10000)

-- ==========================================
-- 無音監視ループ: 10秒ごとに催促再生
-- ==========================================
local prompt_count = 0
local last_asr_time = os.time()
local elapsed = 0
local loop_counter = 0

freeswitch.consoleLog("INFO", "[CALLFLOW] Entering silence monitor loop\n")

-- 無音検知ループ（セッション維持ループ）
while session:ready() do
    freeswitch.msleep(1000)  -- セッション状態に依存せず確実にスリープ
    elapsed = elapsed + 1
    loop_counter = loop_counter + 1
    
    -- デバッグ: ループ実行状況を確認（5秒ごと）
    if loop_counter % 5 == 0 then
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] DEBUG Loop iteration=%d, elapsed=%d, session_ready=%s\n", loop_counter, elapsed, tostring(session:ready())))
    end
    
    -- ASR検出タイムスタンプをチェック
    local asr_timestamp = 0
    local f = io.open(asr_timestamp_file, "r")
    if f then
        local content = f:read("*a")
        f:close()
        if content then
            asr_timestamp = tonumber(content) or 0
        end
    end
    
    -- ASR検出があれば、タイムスタンプを更新して催促カウントをリセット
    if asr_timestamp > last_asr_time then
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] ASR detected at timestamp %d\n", asr_timestamp))
        last_asr_time = asr_timestamp
        
        -- ASRハンドラー側で復唱と切断が行われるまで待機（最大10秒）
        freeswitch.consoleLog("INFO", "[CALLFLOW] Speech detected, waiting for ASR handler to process (max 10 seconds)\n")
        local wait_start = os.time()
        while session:ready() and os.difftime(os.time(), wait_start) < 10 do
            freeswitch.msleep(1000)
        end
        -- ASRハンドラー側で切断される想定だが、念のためここでも切断
        if session:ready() then
            freeswitch.consoleLog("INFO", "[CALLFLOW] ASR handler did not hangup, hanging up from Lua\n")
            session:hangup("NORMAL_CLEARING")
        end
        break
    end
    
    -- タイムアウトチェック
    if elapsed >= silence_timeout then
        prompt_count = prompt_count + 1
        
        freeswitch.consoleLog("INFO", string.format("[CALLFLOW] Timeout %d, playing reminder %d\n", elapsed, prompt_count))
        
        if prompt_count <= #reminders then
            -- 催促を再生
            local reminder_path = reminders[prompt_count]
            
            -- 再answerチェック
            if not session:ready() then
                freeswitch.consoleLog("WARNING", "[CALLFLOW] Session not ready, forcing re-answer\n")
                session:answer()
                freeswitch.msleep(500)
            end
            
            if session:ready() then
                -- ファイル存在確認と安全な再生
                if freeswitch.FileExists(reminder_path) then
                    local ok, err = pcall(function()
                        session:execute("playback", reminder_path)
                    end)
                    if ok then
                        freeswitch.consoleLog("INFO", "[CALLFLOW] Playing reminder: " .. reminder_path .. "\n")
                    else
                        freeswitch.consoleLog("ERROR", "[CALLFLOW] Reminder playback failed: " .. tostring(err) .. "\n")
                    end
                else
                    freeswitch.consoleLog("WARNING", "[CALLFLOW] Reminder file missing: " .. reminder_path .. "\n")
                end
                
                -- playback後に通話が閉じていないか確認
                if not session:ready() then
                    freeswitch.consoleLog("WARNING", "[CALLFLOW] Session closed right after reminder playback\n")
                    break
                end
                
                -- 再生後、余韻時間確保（再生完了検知まで）
                freeswitch.msleep(1500)
            else
                freeswitch.consoleLog("WARNING", "[CALLFLOW] Session not ready after re-answer, skipping reminder this cycle\n")
            end
        
            elapsed = 0  -- 催促後、elapsedをリセット
        else
            -- 3回催促後も無反応：切断
            freeswitch.consoleLog("INFO", "[CALLFLOW] No response after 3 prompts → hangup\n")
            session:hangup("NO_ANSWER")
            break
        end
    end
end

freeswitch.consoleLog("INFO", string.format("[LUA] play_audio_sequence end uuid=%s\n", uuid))

