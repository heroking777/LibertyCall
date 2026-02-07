freeswitch.consoleLog("info", "--- Lua Script Started (Final Fix) ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- コーデックをPCMUに強制（念のため）
    session:execute("export", "absolute_codec_string=PCMU")
    
    -- 宛先を 127.0.0.1 ではなく、実IP (160.251.170.253) に設定
    -- これによりOSのループバック制限を回避し、Gateway (0.0.0.0:7002) に到達させる
    local target_ip = "160.251.170.253"
    local target_port = "7002"
    
    freeswitch.consoleLog("info", "--- Starting rtp_stream to " .. target_ip .. ":" .. target_port .. " ---\n")
    session:execute("rtp_stream", "remote_addr=" .. target_ip .. ",remote_port=" .. target_port .. ",payload=0")
    
    -- RTP生成用の音声再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    freeswitch.consoleLog("info", "--- Test completed ---\n")
end
