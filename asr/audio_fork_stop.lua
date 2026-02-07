freeswitch.consoleLog("NOTICE", "[AF_STOP] ENTER argv1=" .. tostring(argv and argv[1]) .. " sess=" .. tostring(session and session:get_uuid()) .. "\n")

-- 既存の処理（もしあれば）
if argv and argv[1] then
    local uuid = argv[1]
    freeswitch.consoleLog("NOTICE", "[AF_STOP] STOPPING uuid=" .. tostring(uuid) .. "\n")
    -- audio_fork停止処理
    api = freeswitch.API()
    local result = api:executeString("uuid_audio_fork " .. uuid .. " stop")
    freeswitch.consoleLog("NOTICE", "[AF_STOP] RESULT=" .. tostring(result) .. "\n")
end
