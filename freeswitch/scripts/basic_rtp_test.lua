-- 最も基本的なRTP生成テスト
freeswitch.consoleLog("info", "--- BASIC RTP TEST ---\n")

if session:ready() then
    freeswitch.consoleLog("info", "--- Session ready ---\n")
    session:answer()
    freeswitch.consoleLog("info", "--- Call answered ---\n")
    
    -- 最も単純なRTPストリーム（デフォルト設定）
    freeswitch.consoleLog("info", "--- Starting basic rtp_stream ---\n")
    session:execute("rtp_stream", "127.0.0.1:7002")
    
    -- トーン生成でRTPを強制的に生成
    freeswitch.consoleLog("info", "--- Generating tone to force RTP ---\n")
    session:execute("playback", "tone_stream://%(2000,4000,440)")
    
    freeswitch.consoleLog("info", "--- Test completed ---\n")
else
    freeswitch.consoleLog("err", "--- No session ---\n")
end
