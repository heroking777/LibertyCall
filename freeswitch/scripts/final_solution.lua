freeswitch.consoleLog("info", "--- Final Solution Started ---\n")

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
    
    -- FFmpegで変換して外部IPに送信
    local cmd = "ffmpeg -re -i " .. temp_file .. " -f s16le -ar 8000 -ac 1 -acodec pcm_mulaw -f mulaw /tmp/temp_audio.ulaw && nc -u 160.251.170.253 7002 < /tmp/temp_audio.ulaw &"
    freeswitch.consoleLog("info", "--- Executing: " .. cmd .. " ---\n")
    api:execute("system", cmd)
end
