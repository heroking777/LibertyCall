"""
会話フロー管理（クライアント設定対応版）
"""
import json
import logging
import os
from typing import Tuple, List, Dict, Any

logger = logging.getLogger(__name__)

# クライアント設定キャッシュ
_config_cache: Dict[str, dict] = {}

def load_client_config(client_id: str) -> dict:
    """クライアント設定を読み込む（キャッシュ付き）"""
    if client_id in _config_cache:
        return _config_cache[client_id]
    
    config_path = f"/opt/libertycall/clients/{client_id}/config/dialogue_config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            _config_cache[client_id] = config
            logger.info(f"[DIALOGUE] Loaded config for client {client_id}")
            return config
    except Exception as e:
        logger.warning(f"[DIALOGUE] Config not found for {client_id}, using default: {e}")
        return {
            "patterns": [],
            "default_response": "114"
        }

def get_response(
    text: str,
    phase: str = "QA",
    state: dict = None,
    client_id: str = "000",
    **kwargs
) -> Tuple[List[str], str, dict]:
    """
    発話テキストに対する応答を返す
    """
    if state is None:
        state = {}
    
    config = load_client_config(client_id)
    text_clean = text.strip() if text else ""
    
    logger.info(f"[DIALOGUE] get_response client={client_id} phase={phase} text={text_clean}")
    
    # 無入力回数チェック
    no_input_count = state.get('no_input_count', 0)
    if not text_clean:
        no_input_count += 1
        state['no_input_count'] = no_input_count
        
        # 無入数回数制限チェック
        if no_input_count >= config.get("no_input_count_limit", 2):
            logger.info(f"[DIALOGUE] no_input_count limit reached: {no_input_count}")
            return [config.get("retry_exceeded_response", "0604")], phase, state
        
        return [config.get("timeout_response", "003")], phase, state
    else:
        # 入力があったので無入力回数をリセット
        state['no_input_count'] = 0
    
    # 再試行回数チェック
    retry_count = state.get('retry_count', 0)
    retry_limit = config.get("retry_limit", 1)
    
    # patterns配列形式をチェック（新形式）
    patterns = config.get("patterns", [])
    if isinstance(patterns, list):
        # sales_check済みなら営業系キーワードで即確定
        if state.get('sales_check_done'):
            sales_keywords = ['ご案内', '案内', '提案', '営業', 'そうです', 'はい']
            for kw in sales_keywords:
                if kw in text_clean:
                    logger.info("[SALES] sales_confirm triggered after sales_check")
                    state['sales_check_done'] = False
                    state['action'] = 'hangup'
                    return ['094', '087'], phase, state
        for pattern in patterns:
            # phase条件チェック（指定されている場合のみ）
            pattern_phase = pattern.get("phase")
            if pattern_phase and pattern_phase != phase:
                continue
                
            keywords = pattern.get("keywords", [])
            for kw in keywords:
                if kw in text_clean:
                    response = pattern.get("response", config.get("default_response", "002"))
                    followup = pattern.get("followup")
                    action = pattern.get("action")
                    next_phase = pattern.get("next_phase", phase)
                    
                    logger.info(f"[DIALOGUE] pattern matched: keyword={kw} response={response} followup={followup} action={action} next_phase={next_phase}")
                    
                    # 応答リストを構築
                    responses = [response]
                    
                    # followupがあれば追加
                    if followup:
                        if isinstance(followup, list):
                            responses.extend(followup)
                        else:
                            responses.append(followup)
                    
                    # actionをstateに保存
                    if action:
                        state['action'] = action
                        logger.info(f"[DIALOGUE] action set: {action}")
                    
                    # sales_check状態の管理
                    pattern_name = pattern.get("name", "")
                    if pattern_name == "sales_check":
                        state['sales_check_done'] = True
                        logger.info("[SALES] sales_check triggered, setting state")
                    
                    # 再試行回数をリセット
                    state['retry_count'] = 0
                    
                    return responses, next_phase, state
    
    # greetings辞書形式をチェック（旧形式・000用）
    greetings = config.get("greetings", {})
    for keyword, response in greetings.items():
        if keyword in text_clean:
            logger.info(f"[DIALOGUE] greeting matched: {keyword}")
            if isinstance(response, list):
                return response, phase, state
            return [response], phase, state
    
    # custom_patterns辞書形式をチェック（旧形式）
    custom_patterns = config.get("custom_patterns", {})
    for pattern_name, pattern_cfg in custom_patterns.items():
        keywords = pattern_cfg.get("keywords", [])
        for kw in keywords:
            if kw in text_clean:
                response = pattern_cfg.get("response", config.get("default_response", ["114"]))
                next_phase = pattern_cfg.get("next_phase", phase)
                logger.info(f"[DIALOGUE] custom pattern matched: {pattern_name}")
                if isinstance(response, list):
                    return response, next_phase, state
                return [response], next_phase, state
    
    # デフォルト応答
    default = config.get("default_response", "114")
    logger.info(f"[DIALOGUE] default response: {default}")
    
    # 再試行回数チェック
    if retry_count < retry_limit:
        state['retry_count'] = retry_count + 1
        logger.info(f"[DIALOGUE] retry count: {retry_count + 1}/{retry_limit}")
    else:
        # 再試行回数超過
        logger.info(f"[DIALOGUE] retry limit exceeded: {retry_count}/{retry_limit}")
        default = config.get("retry_exceeded_response", "0604")
        state['retry_count'] = 0  # リセット
        phase = "transfer_confirm"  # 転送確認phaseに遷移
    
    if isinstance(default, list):
        return default, phase, state
    return [default], phase, state

def get_action(state: dict) -> str:
    """
    stateからアクションを取得してクリア
    """
    action = state.get('action')
    if action:
        state.pop('action', None)  # アクションをクリア
        logger.info(f"[DIALOGUE] action retrieved: {action}")
    return action or ""

