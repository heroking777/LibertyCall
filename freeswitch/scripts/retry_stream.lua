freeswitch.consoleLog("info", "--- Lua Script: Raw Stream Retry ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 設定
    local gateway_ip = "160.251.170.253"
    local gateway_port = "7002"
    -- 拡張子を .r8 (Raw 8k) に変更。これならFreeSWITCHは認識するはず。
    local file_path = "/tmp/stream_buffer.r8"
    
    -- 1. ファイル初期化
    os.execute("rm -f " .. file_path)
    os.execute("touch " .. file_path)
    
    -- 2. 転送プロセス起動
    -- -F: ファイルがローテートされても追跡（念のため）
    -- -c +1: 先頭からバイト単位で出力
    -- nc: 宛先へUDP送信
    local stream_cmd = "tail -F -c +1 " .. file_path .. " | nc -u " .. gateway_ip .. " " .. gateway_port .. " &"
    freeswitch.consoleLog("info", "--- Starting Streamer: " .. stream_cmd .. " ---\n")
    os.execute(stream_cmd)
    
    -- 3. 録音開始
    local uuid = session:get_uuid()
    api = freeswitch.API()
    -- .r8 拡張子で録音開始
    api:execute("uuid_record", uuid .. " start " .. file_path)
    freeswitch.consoleLog("info", "--- Recording started to " .. file_path .. " ---\n")
    
    -- 4. 音声再生（長めに！）
    -- バッファリングを超えて書き込ませるため、連続して再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(1000)
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(1000)
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    
    -- 5. 終了処理
    api:execute("uuid_record", uuid .. " stop " .. file_path)
    
    -- プロセス掃除（念のため）
    os.execute("pkill -f 'tail -F -c +1 " .. file_path .. "'")
    
    freeswitch.consoleLog("info", "--- Retry Stream Completed ---\n")
end
