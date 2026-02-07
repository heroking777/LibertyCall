-- 代替構文テスト2: streamFileを使用
freeswitch.consoleLog("INFO", "[ALT_TEST2] Script started\n")
if session then
    session:answer()
    freeswitch.consoleLog("INFO", "[ALT_TEST2] Using streamFile syntax\n")
    session:streamFile("rtp_stream::{remote_ip=127.0.0.1,remote_port=7002,payload_type=8}file_string:///usr/local/freeswitch/sounds/custom/000-000.wav")
    freeswitch.consoleLog("INFO", "[ALT_TEST2] StreamFile started\n")
    session:sleep(3000000)
else
    freeswitch.consoleLog("ERR", "[ALT_TEST2] No session\n")
end
