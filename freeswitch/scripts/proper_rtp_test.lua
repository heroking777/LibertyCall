-- ログ出力
freeswitch.consoleLog("info", "--- Lua Script Started ---\n")

-- 1. 通話を確立する（重要：これで200 OKが返り、RTPポートが開く）
if session:ready() then
    freeswitch.consoleLog("info", "--- Session ready, answering call ---\n")
    session:answer()
    -- SDPが安定するまで少し待つ
    session:sleep(1000)
    freeswitch.consoleLog("info", "--- Call answered, SDP should be stable ---\n")
end

-- 2. rtp_stream を開始（エラーハンドリング付き）
-- 宛先: 127.0.0.1:7002, Payload: 0 (PCMU)
freeswitch.consoleLog("info", "--- Starting rtp_stream ---\n")
session:execute("rtp_stream", "remote_addr=127.0.0.1,remote_port=7002,payload=0")
freeswitch.consoleLog("info", "--- rtp_stream started ---\n")

-- 3. 【重要】RTPパケットを生成するために音声を再生し続ける
-- 無音だとパケットが飛ばない可能性があるため、連続音声を流す
freeswitch.consoleLog("info", "--- Playing Audio to generate RTP ---\n")
-- 無限ループで音声を流し続ける（テスト用）
local counter = 0
while session:ready() and counter < 10 do
    counter = counter + 1
    freeswitch.consoleLog("info", "--- Playing audio iteration " .. counter .. " ---\n")
    -- 利用可能な音声ファイルを再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(1000)
end

freeswitch.consoleLog("info", "--- Lua Script Completed ---\n")
