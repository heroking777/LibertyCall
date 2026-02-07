-- 最小テストスクリプト
freeswitch.consoleLog("INFO", "[TEST_LUA] Script executed successfully\n")
if session then
    freeswitch.consoleLog("INFO", "[TEST_LUA] Session exists: " .. session:get_uuid() .. "\n")
    session:answer()
    session:execute("external_rtp", "127.0.0.1:7002")
    freeswitch.consoleLog("INFO", "[TEST_LUA] External RTP started\n")
else
    freeswitch.consoleLog("ERR", "[TEST_LUA] No session found\n")
end
