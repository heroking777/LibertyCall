freeswitch.consoleLog("info", "--- Lua Script: File-based Streaming ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 設定
    local gateway_ip = "160.251.170.253"
    local gateway_port = "7002"
    local file_path = "/tmp/stream_buffer.pcmu"
    
    -- 1. ファイルの初期化（空にする）
    os.execute("rm -f " .. file_path)
    os.execute("touch " .. file_path)
    
    -- 2. 転送プロセス (tail + nc) をバックグラウンドで起動
    -- -f: 追記を監視
    -- -n +1: 先頭から読み込み
    -- stdbuf -o0: バッファリングを無効化して遅延を減らす（利用可能な場合）
    -- timeout: 通話終了後のゾンビプロセス防止（例: 60秒で強制終了）
    local stream_cmd = "timeout 60s tail -f -n +1 " .. file_path .. " | nc -u " .. gateway_ip .. " " .. gateway_port .. " &"
    
    freeswitch.consoleLog("info", "--- Starting Streamer: " .. stream_cmd .. " ---\n")
    os.execute(stream_cmd)
    
    -- 3. 録音開始 (通常ファイルへの書き込みなのでブロックされない)
    -- .pcmu 拡張子でRaw u-lawデータを書き込む
    local uuid = session:get_uuid()
    api = freeswitch.API()
    -- Media Bugとして録音開始
    api:execute("uuid_record", uuid .. " start " .. file_path)
    
    freeswitch.consoleLog("info", "--- Recording started to " .. file_path .. " ---\n")
    
    -- 4. 音声再生 (テスト用)
    -- これがファイルに書き込まれ、即座にtailで転送される
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    -- 念のため長めに待機
    session:sleep(2000)
    
    -- 5. 終了処理
    api:execute("uuid_record", uuid .. " stop " .. file_path)
    -- ファイルは残るが、次回の実行時に初期化される
    
    freeswitch.consoleLog("info", "--- Final Streaming Completed ---\n")
end
