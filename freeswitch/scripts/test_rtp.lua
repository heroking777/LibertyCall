freeswitch.consoleLog("info", "--- Lua Script Started ---\n")

-- 1. rtp_stream をセットアップ（READストリームを対象にする）
-- 相手につながる前にセットしても、Media Bugとして機能するはずです
session:execute("rtp_stream", "remote_addr=127.0.0.1,remote_port=7002,payload=0")
freeswitch.consoleLog("info", "--- rtp_stream executed ---\n")

-- 2. トーン生成内線 (9998) に接続する
-- これにより、9998からの音声がこのチャンネルの「READストリーム」に入ってきます
freeswitch.consoleLog("info", "--- Bridging to Tone Generator (9998) ---\n")
session:execute("bridge", "loopback/9998")

-- bridgeが終了したら終了
freeswitch.consoleLog("info", "--- Lua Script Finished ---\n")
