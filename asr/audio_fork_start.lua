-- audio_fork_start.lua (SAFE)
-- RULES:
--  - NEVER call synchronous uuid_audio_fork start (it can block)
--  - Use bgapi only
--  - Guard against double-start

local api = freeswitch.API()

local function log(lvl, msg)
  freeswitch.consoleLog(lvl, "[AF_START] " .. msg .. "\n")
end

local function lua_log(msg)
  freeswitch.consoleLog("INFO", "[AF_LUA] " .. msg .. "\n")
end

local function exec(cmd)
  local ret = api:executeString(cmd)
  if not ret then return "" end
  return ret:gsub("\r", "")
end

local function uuid_exists(uuid)
  local ret = exec("uuid_exists " .. uuid)
  local ok = ret:match("true") ~= nil
  lua_log(string.format("uuid_exists uuid=%s ok=%s raw=%s", uuid, tostring(ok), ret:gsub("\n", " ")))
  return ok
end

local function fork_status(uuid)
  local ret = exec("uuid_audio_fork " .. uuid .. " status")
  local state = ret:match("state=([A-Z_]+)")
  lua_log(string.format("status uuid=%s state=%s raw=%s", uuid, state or "ERR", ret:gsub("\n", " ")))
  if ret:match("^%+OK") and state then
    return state
  end
  return nil
end

lua_log("hangup hook via api_hangup_hook")

local function bug_line_for_uuid(bugs, uuid)
  if not bugs or bugs == "" then return "" end
  for line in bugs:gmatch("[^\n]+") do
    if line:find(uuid, 1, true) then
      return line
    end
  end
  return ""
end

local function log_bug_snapshot(tag, uuid)
  local bugs = api:executeString("show bugs") or ""
  local line = bug_line_for_uuid(bugs, uuid)
  if line ~= "" then
    log("NOTICE", tag .. " bug_found uuid=" .. uuid .. " line=" .. line)
  else
    log("NOTICE", tag .. " bug_not_found uuid=" .. uuid)
  end
end

local function dump_keylines(uuid)
  local out = api:executeString("uuid_dump " .. uuid) or ""
  local keys = {}
  for line in out:gmatch("[^\r\n]+") do
    if line:match("^Channel%-State:") or
       line:match("^Answer%-State:") or
       line:match("^Read%-Codec%-Name:") or line:match("^Read%-Codec%-Rate:") or
       line:match("^Write%-Codec%-Name:") or line:match("^Write%-Codec%-Rate:") then
      table.insert(keys, line)
    end
  end
  log("NOTICE", "uuid_dump_keylines uuid=" .. uuid .. " | " .. table.concat(keys, " | "))
end

local function spawn_delayed_stop(uuid, delay_sec)
  -- sched_api が無い環境向け: OS側で遅延 stop を投げる
  -- uuid は 0-9a-f- のみ想定（外部入力は入れない運用）
  local fscli = "/usr/local/freeswitch/bin/fs_cli"
  local cmd = string.format(
    "nohup bash -lc 'sleep %d; %s -x \"bgapi uuid_audio_fork %s stop\" >/dev/null 2>&1' >/dev/null 2>&1 &",
    delay_sec, fscli, uuid
  )
  os.execute(cmd)
  log("NOTICE", "scheduled-stop(nohup) delay=" .. tostring(delay_sec) .. "s uuid=" .. uuid)
end

if not session or not session:ready() then
  log("ERR", "session not ready")
  return
end

local wsurl = session:getVariable("af_ws_url") or ""
local mode  = session:getVariable("af_mode") or "mono"
local rate  = session:getVariable("af_rate") or "16k"
local metadata_b64 = session:getVariable("af_metadata") or "{}"

lua_log(string.format("argv wsurl='%s' mode='%s' rate='%s' meta='%s'", wsurl, mode, rate, metadata_b64))

if wsurl == "" then
  lua_log("wsurl empty -> skip")
  return
end

local uuid = session:get_uuid()
local running = session:getVariable("audio_fork_running")
if running == "1" then
  log("NOTICE", "skip: already running uuid=" .. uuid)
  return
end

-- H4対策：メディアlegを探してfork対象にする
local dump = api:executeString("uuid_dump " .. uuid) or ""
local bridge_uuid = ""
local signal_bond = ""
local other_leg_uuid = ""

for line in dump:gmatch("[^\r\n]+") do
  if line:match("variable_bridge_uuid") then
    bridge_uuid = line:match("variable_bridge_uuid:%s*([^\r\n]+)") or ""
  elseif line:match("variable_signal_bond") then
    signal_bond = line:match("variable_signal_bond:%s*([^\r\n]+)") or ""
  elseif line:match("variable_other_leg_uuid") then
    other_leg_uuid = line:match("variable_other_leg_uuid:%s*([^\r\n]+)") or ""
  end
end

local target_uuid = bridge_uuid or signal_bond or other_leg_uuid or uuid
if target_uuid ~= uuid then
  log("NOTICE", "target_peer uuid=" .. target_uuid .. " bridge=" .. bridge_uuid .. " bond=" .. signal_bond .. " other=" .. other_leg_uuid)
else
  log("NOTICE", "target_self uuid=" .. uuid)
end

-- target_uuidが空の場合は自UUIDにフォールバック（Operation Failed防止）
if not target_uuid or target_uuid == "" then
  target_uuid = uuid
  log("NOTICE", "target_fallback uuid=" .. uuid)
end

lua_log(string.format("enter uuid=%s ws=%s", target_uuid, wsurl or ""))

local exists = uuid_exists(target_uuid)
if not exists then
  lua_log(string.format("decision uuid=%s action=SKIP_EXISTS_FALSE", target_uuid))
  return
end

local current_state = fork_status(target_uuid)
if current_state == "CONNECTED" then
  lua_log(string.format("decision uuid=%s action=SKIP_CONNECTED state=%s", target_uuid, current_state))
  return
end

lua_log(string.format("decision uuid=%s action=START state=%s", target_uuid, current_state or "nil"))

-- args (single source of truth)
local metadata_arg

-- build command with metadata (default to {})
if metadata_b64 ~= "" then
  metadata_arg = metadata_b64
  log("NOTICE", "has_metadata target_uuid=" .. target_uuid .. " b64_len=" .. tostring(#metadata_arg))
else
  metadata_arg = "{}"
  log("NOTICE", "no_metadata target_uuid=" .. target_uuid .. " use_default={}")
end

local cmd = string.format("uuid_audio_fork %s start %s %s %s %s", target_uuid, wsurl, mode, rate, metadata_arg)
freeswitch.consoleLog("NOTICE", string.format("[AF_FORK] cmd=%s\n", cmd))

-- delay start inside lua (avoid external nohup/fs_cli)
local START_DELAY_MS = 300
log("NOTICE", "scheduled-start delay=" .. tostring(START_DELAY_MS/1000) .. "s uuid=" .. uuid)
freeswitch.msleep(START_DELAY_MS)

-- execute api command directly and capture output
local ret = api:executeString(cmd) or ""
freeswitch.consoleLog("NOTICE", string.format("[AF_FORK] res=%s\n", ret:gsub("\n", " ")))

log("NOTICE", "start_ret target_uuid=" .. target_uuid .. " ret=" .. ret)
lua_log(string.format("start uuid=%s rc=%s", target_uuid, ret:gsub("\n", " ")))

-- api returns "+OK" on success, "-ERR" on failure
if ret:match("^%+OK") then
  api:executeString("uuid_setvar " .. target_uuid .. " audio_fork_running 1")
  session:setVariable("audio_fork_running", "1")
  session:setVariable("audio_fork_uuid", target_uuid)
  session:setVariable("audio_fork_ws", wsurl)
  session:setVariable("audio_fork_started_at", os.date("!%Y-%m-%dT%H:%M:%SZ"))
  log("NOTICE", "accepted target_uuid=" .. target_uuid .. " wsurl=" .. wsurl .. " ret=" .. ret)
  
  -- media bug attach が成功しているかを即確認（ログは最小）
  log_bug_snapshot("BUGCHK1", target_uuid)
  freeswitch.msleep(250)
  log_bug_snapshot("BUGCHK2", target_uuid)
  
  -- capture true channel state/codec right after start
  dump_keylines(target_uuid)
  
  -- 8秒後に stop を必ず投げる（hook/sched_apiに依存しない）
  -- spawn_delayed_stop(uuid, 8)
else
  log("ERR", "rejected uuid=" .. uuid .. " wsurl=" .. wsurl .. " ret=" .. ret)
end
