freeswitch.consoleLog("info", "--- Fixed Workaround Started ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    local uuid = session:get_uuid()
    api = freeswitch.API()
    
    -- 拡張子付きパイプに録音開始
    freeswitch.consoleLog("info", "--- Starting recording to /tmp/rtp_pipe.wav ---\n")
    api:execute("uuid_record", uuid .. " start /tmp/rtp_pipe.wav")
    
    -- テスト用の音声再生（これがパイプ経由でRTPになる）
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 録音停止
    api:execute("uuid_record", uuid .. " stop /tmp/rtp_pipe.wav")
    freeswitch.consoleLog("info", "--- Recording stopped ---\n")
end
