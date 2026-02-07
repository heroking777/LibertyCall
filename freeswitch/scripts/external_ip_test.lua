-- 外部IPでのRTPテスト
freeswitch.consoleLog("info", "--- EXTERNAL IP TEST ---\n")

if session:ready() then
    session:answer()
    session:sleep(1000)
    
    -- 外部IPアドレスでテスト
    local external_ip = "160.251.170.253"
    freeswitch.consoleLog("info", "--- Testing rtp_stream to external IP: " .. external_ip .. ":7002 ---\n")
    session:execute("rtp_stream", "remote=" .. external_ip .. ":7002")
    
    session:sleep(2000)
    
    session:execute("playback", "tone_stream://%(2000,4000,440)")
    
    freeswitch.consoleLog("info", "--- Test completed ---\n")
end
