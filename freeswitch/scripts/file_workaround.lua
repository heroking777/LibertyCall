freeswitch.consoleLog("info", "--- File-based Workaround Started ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    local uuid = session:get_uuid()
    api = freeswitch.API()
    
    -- 一時ファイルに録音開始
    local temp_file = "/tmp/temp_audio.wav"
    freeswitch.consoleLog("info", "--- Recording to temporary file: " .. temp_file .. " ---\n")
    api:execute("uuid_record", uuid .. " start " .. temp_file)
    
    -- テスト用の音声再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 録音停止
    api:execute("uuid_record", uuid .. " stop " .. temp_file)
    freeswitch.consoleLog("info", "--- Recording stopped ---\n")
    
    -- FFmpegでファイルをRTPとして送信
    local cmd = "ffmpeg -re -i " .. temp_file .. " -acodec pcm_mulaw -f rtp -payload_type 0 rtp://127.0.0.1:7002 &"
    freeswitch.consoleLog("info", "--- Executing: " .. cmd .. " ---\n")
    api:execute("system", cmd)
end
