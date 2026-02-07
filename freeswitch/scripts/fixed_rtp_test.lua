-- 修正版RTPテスト
freeswitch.consoleLog("info", "--- FIXED RTP TEST ---\n")

if session:ready() then
    session:answer()
    session:sleep(1000)
    
    -- rtp_streamの正しい構文を試す
    freeswitch.consoleLog("info", "--- Testing rtp_stream with correct syntax ---\n")
    -- 構文1: 基本形式
    session:execute("rtp_stream", "127.0.0.1:7002")
    
    -- 構文2: パラメータ形式
    -- session:execute("rtp_stream", "remote=127.0.0.1:7002")
    
    -- 構文3: 詳細パラメータ
    -- session:execute("rtp_stream", "{remote_ip=127.0.0.1,remote_port=7002}")
    
    session:sleep(2000)
    
    -- RTPを強制生成するための音声再生
    session:execute("playback", "tone_stream://%(2000,4000,440)")
    
    freeswitch.consoleLog("info", "--- Test completed ---\n")
end
