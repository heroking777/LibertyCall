-- /opt/libertycall/asr/af_sched.lua : sched_api wrapper via Lua
local api = freeswitch.API()

local function log_err(msg)
  freeswitch.consoleLog("ERR", "[AF_LUA] " .. msg .. "\n")
end

local tag = (argv and argv[1]) or ""
local uuid = (argv and argv[2]) or ""
local bleg_uuid = (argv and argv[3]) or ""

log_err(string.format("SCHED_START tag=%s uuid=%s bleg=%s", tag, uuid, bleg_uuid))

-- CANARY: sched_api +1 none echo AF_CANARY_OK
if tag == "CANARY" then
  local result = api:executeString("sched_api +1 none echo AF_CANARY_OK")
  log_err(string.format("CANARY ret=%s", result or "EMPTY"))
  return
end

-- T0/T1/T2: luarun af_probe.lua
if tag == "T0" or tag == "T1" or tag == "T2" then
  local delay = "1"
  if tag == "T1" then delay = "2" end
  if tag == "T2" then delay = "3" end
  
  local cmd = string.format("sched_api +%s none luarun /opt/libertycall/asr/af_probe.lua %s %s %s", delay, tag, uuid, bleg_uuid)
  log_err(string.format("EXEC cmd=%s", cmd))
  
  local result = api:executeString(cmd)
  log_err(string.format("SCHED ret=%s", result or "EMPTY"))
  
  -- uuid_broadcast for media injection
  if tag == "T0" then
    local broadcast_cmd1 = string.format("sched_api +1.2 none uuid_broadcast %s /tmp/af_tone_8k.wav both", uuid)
    local broadcast_cmd2 = string.format("sched_api +1.2 none uuid_broadcast %s /tmp/af_tone_8k.wav both", bleg_uuid)
    
    local result1 = api:executeString(broadcast_cmd1)
    local result2 = api:executeString(broadcast_cmd2)
    
    log_err(string.format("BROADCAST1 ret=%s", result1 or "EMPTY"))
    log_err(string.format("BROADCAST2 ret=%s", result2 or "EMPTY"))
  end
end

log_err(string.format("SCHED_END tag=%s", tag))
