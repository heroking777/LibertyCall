-- デバッグテスト
freeswitch.consoleLog("INFO", "[DEBUG_TEST] Script started\n")
if session then
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Session exists: " .. tostring(session:get_uuid()) .. "\n")
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Answering call\n")
    session:answer()
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Call answered\n")
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Starting RTP stream\n")
    session:execute("rtp_stream", "remote=127.0.0.1:7002")
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] RTP stream started\n")
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Sleeping for 5 seconds\n")
    session:sleep(5000000)
    freeswitch.consoleLog("INFO", "[DEBUG_TEST] Script completed\n")
else
    freeswitch.consoleLog("ERR", "[DEBUG_TEST] No session found\n")
end
