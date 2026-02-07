freeswitch.consoleLog("info", "--- Lua Script Started (Workaround Mode) ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 重要: パイプへの書き込みを開始
    -- これにより、音声データが /tmp/rtp_pipe_7002 に流れ、
    -- 待機中の ffmpeg がそれを拾って RTP として 7002 に投げます。
    freeswitch.consoleLog("info", "--- Starting recording to FIFO pipe ---\n")
    
    -- 非同期で録音を開始（通話をブロックしないため）
    local uuid = session:get_uuid()
    api = freeswitch.API()
    
    -- Media Bugとして録音を開始（送受話双方をミックスして送信）
    api:execute("uuid_record", uuid .. " start /tmp/rtp_pipe_7002")
    
    freeswitch.consoleLog("info", "--- Recording started, now playing test audio ---\n")
    
    -- テスト用の音声再生（これがパイプ経由でRTPになる）
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 録音停止
    api:execute("uuid_record", uuid .. " stop /tmp/rtp_pipe_7002")
    freeswitch.consoleLog("info", "--- Recording stopped ---\n")
end
