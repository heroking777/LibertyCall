-- 正しい構文でのRTPテスト
freeswitch.consoleLog("info", "--- CORRECT RTP TEST ---\n")

if session:ready() then
    session:answer()
    session:sleep(1000)
    
    -- 正しいrtp_stream構文
    freeswitch.consoleLog("info", "--- Starting rtp_stream with correct syntax ---\n")
    session:execute("rtp_stream", "remote=127.0.0.1:7002")
    
    session:sleep(2000)
    
    -- RTPを強制生成するための音声再生
    session:execute("playback", "tone_stream://%(2000,4000,440)")
    
    freeswitch.consoleLog("info", "--- Test completed ---\n")
end
