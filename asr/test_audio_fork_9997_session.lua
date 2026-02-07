api = freeswitch.API()

session:answer()
session:sleep(2000)

local uuid = session:getVariable("uuid")
freeswitch.consoleLog("NOTICE", "[AF_SESSION] UUID: " .. tostring(uuid) .. "\n")

local session_state = api:executeString("uuid_getvar " .. uuid .. " channel_state")
freeswitch.consoleLog("NOTICE", "[AF_SESSION] channel_state: " .. tostring(session_state) .. "\n")

session:execute("playback", "silence_stream://100")
session:sleep(500)

local media_state = api:executeString("uuid_getvar " .. uuid .. " read_codec")
freeswitch.consoleLog("NOTICE", "[AF_SESSION] read_codec: " .. tostring(media_state) .. "\n")

local fork_file = "/tmp/test_fork_" .. uuid .. ".wav"
local fork_cmd = "uuid_audio_fork " .. uuid .. " start " .. fork_file .. " mixed 16000"
freeswitch.consoleLog("NOTICE", "[AF_SESSION] Executing: " .. fork_cmd .. "\n")

local start_ret = api:executeString(fork_cmd)
freeswitch.consoleLog("NOTICE", "[AF_SESSION] start_ret: [" .. tostring(start_ret) .. "]\n")

if start_ret and start_ret:match("^%+OK") then
  freeswitch.consoleLog("NOTICE", "[AF_SESSION] SUCCESS!\n")
  session:streamFile("silence_stream://5000")
  local stop_ret = api:executeString("uuid_audio_fork " .. uuid .. " stop")
  freeswitch.consoleLog("NOTICE", "[AF_SESSION] stop_ret: [" .. tostring(stop_ret) .. "]\n")
else
  freeswitch.consoleLog("ERR", "[AF_SESSION] FAILED: " .. tostring(start_ret) .. "\n")
  local dump = api:executeString("uuid_dump " .. uuid)
  freeswitch.consoleLog("ERR", "[AF_SESSION] uuid_dump:\n" .. tostring(dump) .. "\n")
end

session:hangup()
