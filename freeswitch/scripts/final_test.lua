-- 最終テスト
freeswitch.consoleLog("INFO", "[FINAL_TEST] Script started\n")
if session then
    session:answer()
    freeswitch.consoleLog("INFO", "[FINAL_TEST] Starting RTP with correct syntax\n")
    session:execute("rtp_stream", "127.0.0.1:7002")
    freeswitch.consoleLog("INFO", "[FINAL_TEST] RTP started\n")
    session:sleep(5000000)
else
    freeswitch.consoleLog("ERR", "[FINAL_TEST] No session\n")
end
