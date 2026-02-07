-- 9997専用デバッグLua
local api = freeswitch.API()

local function log(level, msg)
  freeswitch.consoleLog(level, "[AF_9997_DEBUG] " .. msg .. "\n")
end

if not session or not session:ready() then
  log("ERR", "session not ready")
  return
end

session:answer()
session:sleep(1000)

local uuid = session:getVariable("uuid") or ""
log("NOTICE", "Session UUID=" .. uuid)

local bridge_uuid = session:getVariable("bridge_uuid")
local signal_bond = session:getVariable("signal_bond")
local other_leg = session:getVariable("other_leg_unique_id")

log("NOTICE", "bridge_uuid=" .. tostring(bridge_uuid))
log("NOTICE", "signal_bond=" .. tostring(signal_bond))
log("NOTICE", "other_leg=" .. tostring(other_leg))

local target_uuid = bridge_uuid or signal_bond or other_leg or uuid
log("NOTICE", "target_uuid=" .. tostring(target_uuid))

local exists_ret = api:executeString("uuid_exists " .. target_uuid)
log("NOTICE", "uuid_exists=" .. tostring(exists_ret))

if exists_ret ~= "true" then
  log("ERR", "UUID not found, abort")
  session:hangup()
  return
end

local ws_url = "ws://127.0.0.1:9000/"
local metadata_b64 = "eyJ0ZXN0IjoxfQ=="
local fork_cmd = string.format("uuid_audio_fork %s start %s mixed 16000 %s", target_uuid, ws_url, metadata_b64)
log("NOTICE", "Executing: " .. fork_cmd)

local start_ret = api:executeString(fork_cmd)
log("NOTICE", "start_ret=" .. tostring(start_ret))

if start_ret and start_ret:match("^%+OK") then
  session:streamFile("silence_stream://5000")
  local stop_ret = api:executeString("uuid_audio_fork " .. target_uuid .. " stop")
  log("NOTICE", "stop_ret=" .. tostring(stop_ret))
else
  log("ERR", "audio_fork start failed")
end

session:hangup()
