-- production_stream.lua v2 - ASR Recording Version
-- 16kHz/mono/PCM変換付きASR処理

api = freeswitch.API()

if session:ready() then
    local uuid = session:getVariable("uuid")
    local rec = "/usr/local/freeswitch/recordings/asr_probe_" .. uuid .. ".wav"
    local rec16 = "/usr/local/freeswitch/recordings/asr_probe_" .. uuid .. ".16k.wav"

    freeswitch.consoleLog("ERR", "[ASR_VOSK] ENTER production_stream.lua v2 uuid=" .. uuid .. "\n")

    -- 録音開始
    session:execute("record_session", rec)
    freeswitch.consoleLog("ERR", "[REC] " .. rec .. "\n")

    -- 10秒録音
    session:execute("sleep", "10000")
    session:execute("stop_record_session", rec)

    -- 16k/mono/pcmに強制変換（sox）
    local cmd_conv = string.format("sox %q -r 16000 -c 1 -b 16 %q", rec, rec16)
    freeswitch.consoleLog("ERR", "[ASR_VOSK] conv cmd=" .. cmd_conv .. "\n")
    session:execute("system", cmd_conv)

    -- Voskへ
    local cmd_asr = string.format("/usr/local/bin/google_asr.py %q >> /usr/local/freeswitch/log/asr_result.log 2>&1", rec16)
    freeswitch.consoleLog("ERR", "[ASR_VOSK] asr cmd=" .. cmd_asr .. "\n")
    session:execute("system", cmd_asr)
    freeswitch.consoleLog("ERR", "[ASR_VOSK] done file=" .. rec16 .. "\n")

    while session:ready() do
        session:execute("sleep", "1000")
    end
end
