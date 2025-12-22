"""
LibertyCall FlowEngine - JSON定義ベースのフェーズ遷移エンジン

flow.jsonをロードして、条件評価によりフェーズ遷移とテンプレート選択を行う
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger(__name__)


class FlowEngine:
    """
    JSON定義ベースのフェーズ遷移エンジン
    
    各フェーズのtransitionsを評価して、次のフェーズを決定し、
    そのフェーズのtemplatesを返す
    """
    
    def __init__(self, flow_json_path: str):
        """
        FlowEngineを初期化
        
        :param flow_json_path: flow.jsonのパス
        """
        self.logger = logging.getLogger(__name__)
        self.flow = self._load_flow(flow_json_path)
        self.logger.info(f"FlowEngine initialized: {flow_json_path}")
    
    def _load_flow(self, flow_json_path: str) -> Dict[str, Any]:
        """flow.jsonをロード"""
        try:
            with open(flow_json_path, 'r', encoding='utf-8') as f:
                flow = json.load(f)
            self.logger.info(f"Flow loaded: version={flow.get('version')} phases={len(flow.get('phases', {}))}")
            return flow
        except Exception as e:
            self.logger.error(f"Failed to load flow.json: {e}")
            raise
    
    def get_templates(self, phase_name: str) -> List[str]:
        """
        指定されたフェーズのテンプレートIDリストを取得
        
        :param phase_name: フェーズ名（例: "ENTRY", "QA"）
        :return: テンプレートIDのリスト
        """
        phases = self.flow.get("phases", {})
        phase = phases.get(phase_name)
        if not phase:
            self.logger.warning(f"Phase not found: {phase_name}")
            return []
        
        templates = phase.get("templates", [])
        return templates if isinstance(templates, list) else []
    
    def transition(
        self,
        current_phase: str,
        context: Dict[str, Any]
    ) -> str:
        """
        現在のフェーズとコンテキストから次のフェーズを決定
        
        :param current_phase: 現在のフェーズ名
        :param context: コンテキスト情報（intent, keywords, flags等）
        :return: 次のフェーズ名（遷移しない場合は現在のフェーズ名を返す）
        """
        phases = self.flow.get("phases", {})
        phase = phases.get(current_phase)
        
        if not phase:
            self.logger.warning(f"Phase not found: {current_phase}, defaulting to QA")
            return "QA"
        
        transitions = phase.get("transitions", [])
        if not transitions:
            self.logger.debug(f"No transitions defined for phase: {current_phase}")
            return current_phase
        
        # 各遷移条件を評価
        for transition in transitions:
            condition = transition.get("condition", "")
            target = transition.get("target")
            
            if not target:
                continue
            
            if self._eval_condition(condition, context):
                self.logger.info(
                    f"Flow transition: {current_phase} -> {target} "
                    f"(condition: {condition})"
                )
                return target
        
        # 条件にマッチしない場合は現在のフェーズを維持
        self.logger.debug(f"No transition matched for phase: {current_phase}, staying in current phase")
        return current_phase
    
    def _eval_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """
        条件式を評価
        
        サポートする条件:
        - intent == 'XXX'
        - intent != 'XXX'
        - intent == 'XXX' || intent == 'YYY'
        - KEYWORDS を含む（キーワードリストのチェック）
        - user_reply_received == True/False
        - user_voice_detected == True/False
        - timeout
        - その他（デフォルトマッチ）
        
        :param condition: 条件式文字列
        :param context: コンテキスト情報
        :return: 条件が満たされたかどうか
        """
        if not condition or condition.strip() == "":
            return False
        
        condition = condition.strip()
        
        # 「その他」は常にTrue（フォールバック）
        if condition == "その他" or condition == "その他（INQUIRY, UNKNOWN 含む）":
            return True
        
        # intent == 'XXX' のパターン
        if "intent ==" in condition:
            intent = context.get("intent", "")
            # || で分割してOR条件を評価
            if "||" in condition:
                parts = [p.strip() for p in condition.split("||")]
                for part in parts:
                    if "intent ==" in part:
                        # 'XXX' を抽出
                        intent_value = part.split("intent ==")[1].strip().strip("'\"")
                        if intent == intent_value:
                            return True
            else:
                # 単一の intent == 'XXX'
                intent_value = condition.split("intent ==")[1].strip().strip("'\"")
                return intent == intent_value
        
        # intent != 'XXX' のパターン
        if "intent !=" in condition:
            intent = context.get("intent", "")
            intent_value = condition.split("intent !=")[1].strip().strip("'\"")
            return intent != intent_value
        
        # KEYWORDS を含む のパターン
        if "KEYWORDS を含む" in condition or "を含む" in condition:
            keyword_type = None
            if "ENTRY_TRIGGER_KEYWORDS" in condition:
                keyword_type = "ENTRY_TRIGGER_KEYWORDS"
            elif "CLOSING_YES_KEYWORDS" in condition:
                keyword_type = "CLOSING_YES_KEYWORDS"
            elif "CLOSING_NO_KEYWORDS" in condition:
                keyword_type = "CLOSING_NO_KEYWORDS"
            elif "AFTER_085_NEGATIVE_KEYWORDS" in condition:
                keyword_type = "AFTER_085_NEGATIVE_KEYWORDS"
            
            if keyword_type:
                keywords = context.get("keywords", {}).get(keyword_type, [])
                text = context.get("text", "").lower()
                normalized_text = context.get("normalized_text", "").lower()
                
                # キーワードリストのいずれかがテキストに含まれるかチェック
                for keyword in keywords:
                    if keyword.lower() in text or keyword.lower() in normalized_text:
                        return True
        
        # user_reply_received == True/False
        if "user_reply_received" in condition:
            user_reply_received = context.get("user_reply_received", False)
            if "== True" in condition:
                return user_reply_received is True
            elif "== False" in condition:
                return user_reply_received is False
        
        # user_voice_detected == True/False
        if "user_voice_detected" in condition:
            user_voice_detected = context.get("user_voice_detected", False)
            if "== True" in condition:
                return user_voice_detected is True
            elif "== False" in condition:
                return user_voice_detected is False
        
        # timeout
        if "timeout" in condition:
            timeout = context.get("timeout", False)
            return timeout
        
        # intent == 'SALES_CALL' && 初回 のパターン
        if "intent == 'SALES_CALL' && 初回" in condition:
            intent = context.get("intent", "")
            is_first = context.get("is_first_sales_call", False)
            return intent == "SALES_CALL" and is_first
        
        # デフォルト: 条件が評価できない場合はFalse
        self.logger.debug(f"Unsupported condition: {condition}")
        return False
    
    def get_phase_info(self, phase_name: str) -> Optional[Dict[str, Any]]:
        """
        フェーズ情報を取得
        
        :param phase_name: フェーズ名
        :return: フェーズ情報（辞書）またはNone
        """
        phases = self.flow.get("phases", {})
        return phases.get(phase_name)
    
    def get_handoff_flow(self) -> Dict[str, Any]:
        """handoff_flow設定を取得"""
        return self.flow.get("handoff_flow", {})

