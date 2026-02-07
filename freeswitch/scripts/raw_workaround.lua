freeswitch.consoleLog("info", "--- Raw PCM Workaround Started ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    local uuid = session:get_uuid()
    api = freeswitch.API()
    
    -- Raw PCM形式で録音開始
    freeswitch.consoleLog("info", "--- Starting recording to /tmp/rtp_pipe.raw ---\n")
    api:execute("uuid_record", uuid .. " start /tmp/rtp_pipe.raw")
    
    -- テスト用の音声再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 録音停止
    api:execute("uuid_record", uuid .. " stop /tmp/rtp_pipe.raw")
    freeswitch.consoleLog("info", "--- Recording stopped ---\n")
end
