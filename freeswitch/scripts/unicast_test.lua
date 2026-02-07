-- native transport (RTPヘッダがつかないRaw UDPになる可能性が高いが試す価値あり)
freeswitch.consoleLog("info", "--- Unicast Test Started ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    freeswitch.consoleLog("info", "--- Testing unicast command ---\n")
    session:execute("unicast", "rtp 127.0.0.1 7002 0 8000")
    
    session:sleep(2000)
    
    -- テスト用の音声再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    
    freeswitch.consoleLog("info", "--- Unicast Test Completed ---\n")
end
