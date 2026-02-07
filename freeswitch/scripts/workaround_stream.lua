freeswitch.consoleLog("info", "--- Lua Script: NC Workaround Mode ---\n")

if session:ready() then
    session:answer()
    session:sleep(500)
    
    -- 1. 設定値
    local gateway_ip = "160.251.170.253" -- 実IP
    local gateway_port = "7002"
    local pipe_path = "/tmp/gateway_stream.pcmu" -- .pcmu拡張子でRawデータ化
    
    -- 2. 送信プロセス (nc) をバックグラウンドで起動
    -- パイプから読み込み、UDPでGatewayへ送信する
    -- 注意: パイプは読み手がいないと書き込み側がブロックするため、先に起動する
    local nc_cmd = "nc -u " .. gateway_ip .. " " .. gateway_port .. " < " .. pipe_path .. " &"
    freeswitch.consoleLog("info", "--- Starting NC: " .. nc_cmd .. " ---\n")
    os.execute(nc_cmd)
    
    -- 3. 録音開始 (パイプへの書き込み)
    -- uuid_record を使用して、通話音声をパイプに流し込む
    -- 拡張子 .pcmu により、ヘッダなしのRaw u-lawデータになる
    local uuid = session:get_uuid()
    freeswitch.consoleLog("info", "--- Starting Record to Pipe ---\n")
    api = freeswitch.API()
    api:execute("uuid_record", uuid .. " start " .. pipe_path)
    
    -- 4. 音声再生 (テスト用)
    -- これがパイプ経由でGatewayに飛ぶ
    session:streamFile("/usr/local/freeswitch/sounds/custom/000-000.wav")
    session:sleep(2000)
    
    -- 5. 終了処理
    api:execute("uuid_record", uuid .. " stop " .. pipe_path)
    -- ncプロセスはパイプが閉じれば自動終了するはずだが、念のため放置でも実害は少ない
    
    freeswitch.consoleLog("info", "--- Workaround Completed ---\n")
end
