freeswitch.consoleLog("info", "--- Final Workaround: File-based Streaming ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 1. 設定値
    local gateway_ip = "160.251.170.253"
    local gateway_port = "7002"
    local temp_file = "/tmp/stream_audio.pcmu"
    
    -- 2. 録音開始（実時間ストリーミング）
    local uuid = session:get_uuid()
    api = freeswitch.API()
    
    -- 実時間ストリーミングモードで録音開始
    freeswitch.consoleLog("info", "--- Starting Real-time Recording ---\n")
    api:execute("uuid_record", uuid .. " start " .. temp_file)
    
    -- 3. バックグラウンドでファイルを監視し、ncで送信
    -- shスクリプトで実行
    local monitor_cmd = "while true; do if [ -f " .. temp_file .. ".tmp ]; then tail -c 1024 " .. temp_file .. ".tmp | nc -u " .. gateway_ip .. " " .. gateway_port .. "; rm " .. temp_file .. ".tmp; fi; sleep 0.1; done &"
    api:execute("system", monitor_cmd)
    
    -- 4. 音声再生（テスト用）
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(3000)
    
    -- 5. 終了処理
    api:execute("uuid_record", uuid .. " stop " .. temp_file)
    
    -- 監視プロセスを終了
    api:execute("system", "pkill -f 'while true'")
    
    freeswitch.consoleLog("info", "--- Final Workaround Completed ---\n")
end
