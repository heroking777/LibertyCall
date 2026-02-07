freeswitch.consoleLog("info", "--- Record Test Started ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    local uuid = session:get_uuid()
    freeswitch.consoleLog("info", "--- Starting recording to /tmp/final_test.wav ---\n")
    
    api = freeswitch.API()
    api:execute("uuid_record", uuid .. " start /tmp/final_test.wav")
    
    freeswitch.consoleLog("info", "--- Playing test audio ---\n")
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    
    session:sleep(3000)
    
    api:execute("uuid_record", uuid .. " stop /tmp/final_test.wav")
    freeswitch.consoleLog("info", "--- Recording stopped ---\n")
end
