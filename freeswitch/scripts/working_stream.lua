freeswitch.consoleLog("info", "--- Working Stream: WAV-based Streaming ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 設定
    local gateway_ip = "160.251.170.253"
    local gateway_port = "7002"
    local file_path = "/tmp/stream_buffer.wav"
    
    -- 1. ファイルの初期化
    os.execute("rm -f " .. file_path)
    os.execute("touch " .. file_path)
    
    -- 2. 転送プロセス (tail + nc + ffmpeg)
    -- ffmpegでWAVをRaw u-lawに変換して送信
    local stream_cmd = "timeout 60s tail -f -n +1 " .. file_path .. " | ffmpeg -re -f wav -acodec pcm_mulaw -f mulaw - | nc -u " .. gateway_ip .. " " .. gateway_port .. " &"
    
    freeswitch.consoleLog("info", "--- Starting Working Streamer: " .. stream_cmd .. " ---\n")
    os.execute(stream_cmd)
    
    -- 3. 録音開始
    local uuid = session:get_uuid()
    api = freeswitch.API()
    api:execute("uuid_record", uuid .. " start " .. file_path)
    
    freeswitch.consoleLog("info", "--- Recording started to " .. file_path .. " ---\n")
    
    -- 4. 音声再生
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 5. 終了処理
    api:execute("uuid_record", uuid .. " stop " .. file_path)
    
    freeswitch.consoleLog("info", "--- Working Stream Completed ---\n")
end
