#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, tempfile, subprocess, os, json, logging
from pathlib import Path
from datetime import datetime

# stderrをstdoutにリダイレクト（Asteriskがstderrを破棄するため）
sys.stderr = sys.stdout

# ファイル出力によるデバッグログを設定
debug_log_file = '/var/log/asterisk/ai_debug.log'
try:
    logging.basicConfig(
        filename=debug_log_file,
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        filemode='a'
    )
    debug_logger = logging.getLogger('ai_handler')
except Exception as e:
    # ログファイルが作成できない場合は無視
    debug_logger = None

def agi_put(s):
    """AGIコマンドをAsteriskに送信（VERBOSEログ用）"""
    print(s, flush=True)
    if debug_logger:
        debug_logger.debug(f"AGI: {s}")

# AGI環境変数を読み取る（AGIプロトコルの最初のステップ）
def read_agi_env():
    """AGI環境変数を読み取る"""
    env = {}
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            break
        if ':' in line:
            key, value = line.split(':', 1)
            env[key.strip()] = value.strip()
        if line == '':
            break
    return env

# GatewayへのWebSocket接続とinitメッセージ送信
def send_init_to_gateway(agi_env_dict=None):
    """Gatewayにinitメッセージを送信（caller_numberを含む）"""
    try:
        try:
            import websocket
        except ImportError:
            # websocketモジュールがインストールされていない場合はスキップ
            agi_put('VERBOSE "ai_handler: websocket module not available, skipping init message" 1')
            return
        
        # 発信者番号を取得（Asterisk環境変数から）
        # AGIでは環境変数として取得できないため、GET VARIABLEコマンドを使用
        import sys
        
        caller_id_num = None
        
        # ログ出力：AGI環境変数の読み込み状況を確認
        agi_put('VERBOSE "ai_handler: Starting caller_number extraction" 1')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.info("Starting caller_number extraction")
        
        if agi_env_dict:
            agi_put(f'VERBOSE "ai_handler: AGI env dict provided, keys: {list(agi_env_dict.keys())}" 1')
            sys.stdout.flush()
            if debug_logger:
                debug_logger.info(f"AGI env dict provided, keys: {list(agi_env_dict.keys())}")
        
        # 優先順位1: GET VARIABLEコマンドでLC_CALLER_NUMBERを取得（extensions.confで設定したチャネル変数）
        # 注意: AGI環境変数の読み込みが完了してから実行する必要がある
        agi_put('GET VARIABLE LC_CALLER_NUMBER')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.info("Sent GET VARIABLE LC_CALLER_NUMBER")
        
        try:
            response = sys.stdin.readline().strip()
            agi_put(f'VERBOSE "ai_handler: GET VARIABLE LC_CALLER_NUMBER response: [{response}]" 1')
            sys.stdout.flush()
            if debug_logger:
                debug_logger.info(f"GET VARIABLE LC_CALLER_NUMBER response: [{response}]")
            # AGIレスポンス形式: 200 result=1 (value) または 200 result=0 (variable not set)
            if response and response.startswith('200 result='):
                # 200 result=1 (08024152649) の形式から値を抽出
                # または 200 result=0 (variable not set) の場合
                if '(variable not set)' not in response and 'result=0' not in response:
                    # 括弧がある場合
                    match = re.search(r'\(([^)]+)\)', response)
                    if match:
                        caller_id_num = match.group(1)
                        if caller_id_num and caller_id_num.strip() and caller_id_num != "-":
                            caller_id_num = caller_id_num.strip()
                            agi_put(f'VERBOSE "ai_handler: extracted from LC_CALLER_NUMBER variable: {caller_id_num}" 1')
                    else:
                        # 括弧がない場合、result=1の後の値を抽出
                        match = re.search(r'result=1\s+(.+)', response)
                        if match:
                            caller_id_num = match.group(1).strip()
                            if caller_id_num and caller_id_num != "-":
                                agi_put(f'VERBOSE "ai_handler: extracted from LC_CALLER_NUMBER variable (no parens): {caller_id_num}" 1')
        except Exception as e:
            agi_put(f'VERBOSE "ai_handler: failed to read LC_CALLER_NUMBER variable: {e}" 1')
        
        # 優先順位2: GET VARIABLEコマンドでCALLERID(num)を取得（フォールバック）
        if not caller_id_num:
            agi_put('GET VARIABLE CALLERID(num)')
            sys.stdout.flush()  # バッファをフラッシュ
            
            # AGIレスポンスを読み取る（200 result=1 (value) の形式）
            try:
                response = sys.stdin.readline().strip()
                agi_put(f'VERBOSE "ai_handler: GET VARIABLE CALLERID(num) response: [{response}]" 1')
                if response and response.startswith('200 result='):
                    # 200 result=1 (08024152649) の形式から値を抽出
                    if '(variable not set)' not in response and 'result=0' not in response:
                        # 括弧がある場合
                        match = re.search(r'\(([^)]+)\)', response)
                        if match:
                            caller_id_num = match.group(1)
                            if caller_id_num and caller_id_num.strip() and caller_id_num != "-":
                                caller_id_num = caller_id_num.strip()
                                agi_put(f'VERBOSE "ai_handler: extracted from GET VARIABLE CALLERID(num): {caller_id_num}" 1')
                        else:
                            # 括弧がない場合、result=1の後の値を抽出
                            match = re.search(r'result=1\s+(.+)', response)
                            if match:
                                caller_id_num = match.group(1).strip()
                                if caller_id_num and caller_id_num != "-":
                                    agi_put(f'VERBOSE "ai_handler: extracted from GET VARIABLE CALLERID(num) (no parens): {caller_id_num}" 1')
            except Exception as e:
                agi_put(f'VERBOSE "ai_handler: failed to read GET VARIABLE response: {e}" 1')
        
        # 環境変数からも取得を試みる（フォールバック）
        if not caller_id_num:
            # extensions.confで設定した環境変数から取得
            caller_id_num = os.getenv("LC_CALLER_NUMBER")
        if not caller_id_num:
            caller_id_num = os.getenv("CALLERID(num)")
        caller_id_num_var = os.getenv("CALLERIDNUM")
        agi_callerid = os.getenv("agi_callerid", "")
        
        # 優先順位: GET VARIABLE > CALLERID(num) > CALLERIDNUM > agi_callerid
        caller_number = caller_id_num or caller_id_num_var
        
        # agi_callerid から抽出（形式: "09012345678" <name> または 09012345678）
        if not caller_number and agi_callerid:
            # パターン1: "09012345678" <name> 形式
            match = re.match(r'"([^"]+)"', agi_callerid)
            if match:
                caller_number = match.group(1)
            else:
                # パターン2: sip:09012345678@domain 形式
                match = re.search(r'sip:([0-9]+)@', agi_callerid)
                if match:
                    caller_number = match.group(1)
                else:
                    # パターン3: 直接番号が入っている場合
                    # 数字のみを抽出
                    match = re.search(r'([0-9]{10,15})', agi_callerid)
                    if match:
                        caller_number = match.group(1)
                    else:
                        # パターン4: そのまま使用（数字以外の文字が含まれていない場合）
                        if agi_callerid.strip() and not re.search(r'[^0-9]', agi_callerid.strip()):
                            caller_number = agi_callerid.strip()
        
        # デバッグ用：取得したcaller_numberをログに出力
        agi_put(f'VERBOSE "ai_handler: caller_number sources - CALLERID(num)={os.getenv("CALLERID(num)")}, CALLERIDNUM={os.getenv("CALLERIDNUM")}, agi_callerid={os.getenv("agi_callerid")}" 1')
        agi_put(f'VERBOSE "ai_handler: extracted caller_number={caller_number}" 1')
        
        # フォールバック3: AGI環境変数から取得（agi_callerid）
        if not caller_number and agi_env_dict:
            agi_callerid_from_env = agi_env_dict.get('agi_callerid', '')
            if agi_callerid_from_env:
                agi_put(f'VERBOSE "ai_handler: Fallback agi_callerid from AGI env: {agi_callerid_from_env}" 1')
                # agi_callerid から抽出（形式: "08024152649" <name> または 08024152649）
                match = re.match(r'"([^"]+)"', agi_callerid_from_env)
                if match:
                    caller_number = match.group(1)
                    agi_put(f'VERBOSE "ai_handler: Extracted from agi_callerid (quoted): {caller_number}" 1')
                else:
                    # 数字のみを抽出
                    match = re.search(r'([0-9]{10,15})', agi_callerid_from_env)
                    if match:
                        caller_number = match.group(1)
                        agi_put(f'VERBOSE "ai_handler: Extracted from agi_callerid (regex): {caller_number}" 1')
        
        # 最終的なcaller_numberをログ出力
        agi_put(f'VERBOSE "ai_handler: Final caller_number: {caller_number}" 1')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.info(f"Final caller_number: {caller_number}")
        
        # "-" や空文字列の場合は None に変換（Gateway側で "-" として扱われる）
        if caller_number in ("-", "", None):
            caller_number = None
            agi_put('VERBOSE "ai_handler: caller_number is None (converted from empty string)" 1')
            sys.stdout.flush()
            if debug_logger:
                debug_logger.warning("caller_number is None (converted from empty string)")
        
        # call_idを生成（in-YYYYMMDDHHMMSS形式）
        now = datetime.now()
        call_id = f"in-{now.strftime('%Y%m%d%H%M%S')}"
        
        # initメッセージを構築
        init_message = {
            "type": "init",
            "client_id": "000",  # デフォルトクライアントID
            "call_id": call_id,
            "caller_number": caller_number
        }
        
        # GatewayのWebSocket URL（デフォルトはws://127.0.0.1:9001）
        # 環境変数GATEWAY_WS_URLで上書き可能
        ws_url = os.getenv("GATEWAY_WS_URL", "ws://127.0.0.1:9001")
        
        # WebSocket接続してinitメッセージを送信
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(json.dumps(init_message))
        ws.close()
        
        agi_put(f'VERBOSE "ai_handler: sent init message to gateway (call_id={call_id}, caller_number={caller_number})" 1')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.info(f"Sent init message to gateway: call_id={call_id}, caller_number={caller_number}")
        
    except ImportError:
        agi_put('VERBOSE "ai_handler: websocket module not available, skipping init message" 1')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.warning("websocket module not available")
    except Exception as e:
        agi_put(f'VERBOSE "ai_handler: failed to send init message: {e}" 1')
        sys.stdout.flush()
        if debug_logger:
            debug_logger.error(f"Failed to send init message: {e}", exc_info=True)

# AGI環境変数を読み取る（AGIプロトコルの最初のステップ）
# AGIスクリプトが実行されると、最初にstdinから環境変数が送られてくる
# 形式: agi_variable: value\n
# 空行で終了
# ★重要: この処理を最初に実行し、完了してからGET VARIABLEコマンドを実行する
if debug_logger:
    debug_logger.info("AI handler started, reading AGI environment")

agi_env = read_agi_env()
agi_put('VERBOSE "ai_handler: AGI script started" 1')
sys.stdout.flush()
agi_put(f'VERBOSE "ai_handler: AGI env keys: {list(agi_env.keys())}" 1')
sys.stdout.flush()
if debug_logger:
    debug_logger.info(f"AGI env keys: {list(agi_env.keys())}")

if 'agi_callerid' in agi_env:
    agi_put(f'VERBOSE "ai_handler: agi_callerid from env: {agi_env.get("agi_callerid")}" 1')
    sys.stdout.flush()
    if debug_logger:
        debug_logger.info(f"agi_callerid from env: {agi_env.get('agi_callerid')}")

# Gatewayへのinitメッセージ送信（通話開始時）
# agi_envを引数として渡す（send_init_to_gateway内で使用するため）
# ★重要: AGI環境変数の読み込みが完了してから実行する
send_init_to_gateway(agi_env_dict=agi_env)

# 既存のAGI処理
text = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
t = re.sub(r'\s+', ' ', text)
if re.search(r'(営業時間|何時|時間)', t):
    reply = '弊社の営業時間は平日10時から17時半です。'
elif re.search(r'(メール|連絡先)', t):
    reply = 'メールは info アット リバティーコール ドット ジェーピー です。'
else:
    # 担当者ハンドオフの文言は gateway/ai_core 側に任せるため、
    # ここでは中立な確認メッセージだけ返す
    reply = '内容を確認しました。ありがとうございます。'
agi_put(f'VERBOSE "ai_handler: reply={reply}" 1')
agi_put(f'SET VARIABLE AI_REPLY "{reply}"')
# ここでは TTS は未実装。先に占位として無音0.5秒 ulaw を生成して再生確認を行う
out = '/var/lib/asterisk/sounds/ja/ai_temp.ulaw'
Path('/var/lib/asterisk/sounds/ja').mkdir(parents=True, exist_ok=True)
# 500msの無音: soxで生成（インストール済み前提）
subprocess.run(['sox', '-n', '-r', '8000', '-e', 'u-law', '-c', '1', out, 'trim', '0.0', '0.5'], check=False)
agi_put('VERBOSE "ai_handler: synthesized stub ulaw created" 1')
