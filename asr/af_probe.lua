-- af_probe.lua
-- argv: TAG ALEG_UUID BLEG_UUID
local tag  = argv[1] or "NO_TAG"
local aleg = argv[2] or ""
local bleg = argv[3] or ""

local api = freeswitch.API()

local function now()
  return os.date("!%Y%m%dT%H%M%SZ")
end

local function wfile(path, s)
  local f = io.open(path, "a")
  if f then
    f:write(s .. "\n")
    f:close()
  end
end

local function log(line)
  freeswitch.consoleLog("ERR", line .. "\n")
end

local stamp = now()
local pid = tostring(os.time())
local mark = string.format("/tmp/af_probe_exec_%s_%s_%s.txt", tag, pid, stamp)

-- always leave a breadcrumb
wfile(mark, string.format("BEGIN tag=%s aleg=%s bleg=%s ts=%s", tag, aleg, bleg, stamp))
log(string.format("[AF_PROBE_EXEC] begin tag=%s aleg=%s bleg=%s mark=%s", tag, aleg, bleg, mark))

-- PREB_FAIL/OK判定
if tag == "T_PREB" then
  -- bleg_uuidが不正な場合
  if not bleg or bleg == "" or bleg == "EMPTY" or bleg:find("PLACEHOLDER") then
    log(string.format("[AF_PROBE] PREB_FAIL bad_uuid=%s", bleg or "nil"))
    wfile(mark, string.format("PREB_FAIL bad_uuid=%s", bleg or "nil"))
    return
  end
  
  -- uuid_dump API呼び出し
  local success, d = pcall(api.executeString, api, "uuid_dump " .. bleg)
  if not success then
    log(string.format("[AF_PROBE] PREB_FAIL api_ret=exception_error"))
    wfile(mark, "PREB_FAIL api_ret=exception_error")
    return
  end
  
  d = tostring(d or "")
  if not d or d == "" then 
    log(string.format("[AF_PROBE] PREB_FAIL api_ret=empty_dump"))
    wfile(mark, "PREB_FAIL api_ret=empty_dump")
    return 
  end
  
  -- 成功時
  local channel_name = d:match("Channel%-Name:%s*([^\r\n]+)") or "EMPTY"
  local sip_callid = d:match("variable_sip_call_id:%s*([^\r\n]+)") or "EMPTY"
  local sdp_local = d:match("variable_sdp_local:%s*([^\r\n]+)") or "EMPTY"
  local sdp_remote = d:match("variable_sdp_remote:%s*([^\r\n]+)") or "EMPTY"
  
  local has_sdp = (sdp_local:find("v=0") or sdp_remote:find("v=0")) and "YES" or "NO"
  
  log(string.format("[AF_PROBE] PREB_OK bleg=%s chan=%s callid=%s has_sdp=%s", bleg, channel_name, sip_callid, has_sdp))
  wfile(mark, string.format("PREB_OK bleg=%s chan=%s callid=%s has_sdp=%s", bleg, channel_name, sip_callid, has_sdp))
  return
end

-- POSTBR_A判定
if tag == "T_POSTBR_A" then
  -- bleg_uuidが不正な場合
  if not bleg or bleg == "" or bleg == "EMPTY" or bleg:find("PLACEHOLDER") then
    log(string.format("[AF_PROBE] POSTBR_A_FAIL bad_uuid=%s", bleg or "nil"))
    wfile(mark, string.format("POSTBR_A_FAIL bad_uuid=%s", bleg or "nil"))
    return
  end
  
  -- uuid_dump API呼び出し
  local success, d = pcall(api.executeString, api, "uuid_dump " .. bleg)
  if not success then
    log(string.format("[AF_PROBE] POSTBR_A_FAIL api_ret=exception_error"))
    wfile(mark, "POSTBR_A_FAIL api_ret=exception_error")
    return
  end
  
  d = tostring(d or "")
  if not d or d == "" then 
    log(string.format("[AF_PROBE] POSTBR_A_FAIL api_ret=empty_dump"))
    wfile(mark, "POSTBR_A_FAIL api_ret=empty_dump")
    return 
  end
  
  -- 成功時
  local channel_name = d:match("Channel%-Name:%s*([^\r\n]+)") or "EMPTY"
  local sip_callid = d:match("variable_sip_call_id:%s*([^\r\n]+)") or "EMPTY"
  local sdp_local = d:match("variable_sdp_local:%s*([^\r\n]+)") or "EMPTY"
  local sdp_remote = d:match("variable_sdp_remote:%s*([^\r\n]+)") or "EMPTY"
  local bridge_uuid = d:match("variable_bridge_uuid:%s*([^\r\n]+)") or "EMPTY"
  local other_leg_uuid = d:match("variable_other_leg_uuid:%s*([^\r\n]+)") or "EMPTY"
  local rtp_in_pkts = d:match("variable_rtp_audio_inbound_packets:%s*([^\r\n]+)") or "-1"
  local rtp_out_pkts = d:match("variable_rtp_audio_outbound_packets:%s*([^\r\n]+)") or "-1"
  
  local has_sdp = (sdp_local:find("v=0") or sdp_remote:find("v=0")) and "YES" or "NO"
  
  log(string.format("[AF_PROBE] POSTBR_A_OK bleg=%s chan=%s callid=%s has_sdp=%s bridge=%s other=%s rtp_in=%s rtp_out=%s", 
    bleg, channel_name, sip_callid, has_sdp, bridge_uuid, other_leg_uuid, rtp_in_pkts, rtp_out_pkts))
  wfile(mark, string.format("POSTBR_A_OK bleg=%s chan=%s callid=%s has_sdp=%s bridge=%s other=%s rtp_in=%s rtp_out=%s", 
    bleg, channel_name, sip_callid, has_sdp, bridge_uuid, other_leg_uuid, rtp_in_pkts, rtp_out_pkts))
  return
end

local function exec(cmd)
  local ret = api:executeString(cmd) or ""
  ret = tostring(ret)
  return ret
end

-- lightweight uuid_dump fetch (won't parse huge blocks)
local function dump_one(u)
  if not u or u == "" or u == "EMPTY" or u:find("PLACEHOLDER") then
    return "SKIP"
  end
  -- uuid_dump can be big; still ok for 1 shot. store only first 2000 chars
  local d = exec("uuid_dump " .. u)
  if not d or d == "" then return "EMPTYDUMP" end
  local head = d:sub(1, 2000)
  return head
end

local da = dump_one(aleg)
local db = dump_one(bleg)

-- write summaries to file
wfile(mark, "A_DUMP_HEAD=" .. tostring(#da) .. " chars")
wfile(mark, da:gsub("\r",""):gsub("\n","\\n"))
wfile(mark, "B_DUMP_HEAD=" .. tostring(#db) .. " chars")
wfile(mark, db:gsub("\r",""):gsub("\n","\\n"))
wfile(mark, "END")

log(string.format("[AF_PROBE_SUMMARY] tag=%s mark=%s a_len=%s b_len=%s", tag, mark, tostring(#da), tostring(#db)))

-- return something visible to CLI/api
return "OK tag=" .. tag .. " mark=" .. mark .. " a_len=" .. tostring(#da) .. " b_len=" .. tostring(#db)
