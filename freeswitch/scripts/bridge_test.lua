-- bridgeによるRTP送信テスト
freeswitch.consoleLog("info", "--- BRIDGE TEST ---\n")

if session:ready() then
    session:answer()
    session:sleep(1000)
    
    -- Gatewayに直接bridgeする試み
    freeswitch.consoleLog("info", "--- Attempting direct bridge to Gateway ---\n")
    session:execute("bridge", "sofia/lab_open/127.0.0.1:7002")
    
    freeswitch.consoleLog("info", "--- Bridge test completed ---\n")
end
