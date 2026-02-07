-- playbackアプリケーションによるテスト
freeswitch.consoleLog("INFO", "[PLAYBACK_TEST] Script started\n")
if session then
    session:answer()
    freeswitch.consoleLog("INFO", "[PLAYBACK_TEST] Answered call\n")
    session:sleep(1000)
    freeswitch.consoleLog("INFO", "[PLAYBACK_TEST] Playing audio file\n")
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    freeswitch.consoleLog("INFO", "[PLAYBACK_TEST] Audio playback completed\n")
    session:sleep(2000)
else
    freeswitch.consoleLog("ERR", "[PLAYBACK_TEST] No session\n")
end
