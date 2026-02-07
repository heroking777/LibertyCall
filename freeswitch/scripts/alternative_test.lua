-- 代替構文テスト1: 引数をテーブルで渡す
freeswitch.consoleLog("INFO", "[ALT_TEST1] Script started\n")
if session then
    session:answer()
    freeswitch.consoleLog("INFO", "[ALT_TEST1] Using table syntax\n")
    session:execute("stream", "{rtp_payload_type=8,remote_ip=127.0.0.1,remote_port=7002}file_string:///usr/local/freeswitch/sounds/custom/000-000.wav")
    freeswitch.consoleLog("INFO", "[ALT_TEST1] Stream started\n")
    session:sleep(3000000)
else
    freeswitch.consoleLog("ERR", "[ALT_TEST1] No session\n")
end
