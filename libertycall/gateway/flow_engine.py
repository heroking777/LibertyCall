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
    
    def __init__(self, client_id: str = "000", flow_json_path: Optional[str] = None):
        """
        FlowEngineを初期化
        
        :param client_id: クライアントID（例: "000", "001"）
        :param flow_json_path: flow.jsonのパス（指定された場合は優先、未指定の場合はclient_idから自動決定）
        """
        self.logger = logging.getLogger(__name__)
        self.client_id = client_id
        
        # flow_json_pathが指定されていない場合は、client_idから自動決定
        if not flow_json_path:
            # クライアント別のflow.jsonを優先（複数のパスをチェック）
            # 1. /opt/libertycall/clients/{client_id}/flow.json（新形式）
            # 2. /opt/libertycall/config/clients/{client_id}/flow.json（既存形式）
            # 3. /opt/libertycall/config/system/default_flow.json（デフォルト）
            client_flow_path = f"/opt/libertycall/clients/{client_id}/flow.json"
            config_flow_path = f"/opt/libertycall/config/clients/{client_id}/flow.json"
            system_default_path = "/opt/libertycall/config/system/default_flow.json"
            
            if Path(client_flow_path).exists():
                flow_json_path = client_flow_path
            elif Path(config_flow_path).exists():
                flow_json_path = config_flow_path
            else:
                flow_json_path = system_default_path
        
        self.flow = self._load_flow(flow_json_path)
        self.logger.info(f"FlowEngine initialized: client_id={client_id} flow_path={flow_json_path}")
    
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
        指定されたフェーズのテンプレートIDリストを取得（エラーフォールバック対応）
        テンプレートIDの存在チェックも実行
        
        :param phase_name: フェーズ名（例: "ENTRY", "QA"）
        :return: テンプレートIDのリスト
        """
        try:
            phases = self.flow.get("phases", {})
            phase = phases.get(phase_name)
            if not phase:
                self.logger.warning(f"Phase not found: {phase_name}, using fallback template")
                # フォールバック: デフォルトの「聞き取れませんでした」テンプレートを返す
                return ["110"]
            
            templates = phase.get("templates", [])
            if not isinstance(templates, list):
                self.logger.warning(f"Invalid templates format for phase: {phase_name}, using fallback")
                return ["110"]
            
            # テンプレートが空の場合はフォールバック
            if not templates:
                self.logger.warning(f"No templates found for phase: {phase_name}, using fallback")
                return ["110"]
            
            # テンプレートIDの存在チェック
            missing_templates = []
            for template_id in templates:
                audio_dir = Path(f"/opt/libertycall/clients/{self.client_id}/audio")
                audio_file_norm = audio_dir / f"{template_id}_8k_norm.wav"
                audio_file_regular = audio_dir / f"{template_id}_8k.wav"
                
                if not audio_file_norm.exists() and not audio_file_regular.exists():
                    missing_templates.append(template_id)
            
            # 欠落テンプレートがあれば警告を出力
            if missing_templates:
                self.logger.warning(
                    f"Missing template audio files for phase {phase_name}: {missing_templates}"
                )
                # runtime.logにも警告を出力
                runtime_logger = logging.getLogger("runtime")
                runtime_logger.warning(
                    f"[FLOW] Missing template audio: phase={phase_name} templates={missing_templates}"
                )
            
            return templates
        except Exception as e:
            self.logger.exception(f"Error getting templates for phase {phase_name}: {e}")
            # エラー時はフォールバックテンプレートを返す
            return ["110"]
    
    def transition(
        self,
        current_phase: str,
        context: Dict[str, Any]
    ) -> str:
        """
        現在のフェーズとコンテキストから次のフェーズを決定（エラーフォールバック対応）
        
        :param current_phase: 現在のフェーズ名
        :param context: コンテキスト情報（intent, keywords, flags等）
        :return: 次のフェーズ名（遷移しない場合は現在のフェーズ名を返す）
        """
        try:
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
                try:
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
                except Exception as e:
                    # 個別の遷移条件評価でエラーが発生した場合はスキップして次へ
                    self.logger.warning(f"Error evaluating transition condition: {e}, skipping")
                    continue
            
            # 条件にマッチしない場合は現在のフェーズを維持
            # ただし、UNKNOWN intentの場合はQAフェーズへ復帰
            intent = context.get("intent", "")
            if intent == "UNKNOWN" and current_phase != "QA":
                self.logger.info(f"UNKNOWN intent detected, transitioning to QA: phase={current_phase}")
                return "QA"
            
            self.logger.debug(f"No transition matched for phase: {current_phase}, staying in current phase")
            return current_phase
        except Exception as e:
            self.logger.exception(f"Error in FlowEngine.transition: {e}")
            # エラー時は安全なフェーズ（NOT_HEARD）にフォールバック（通話が止まらないように）
            # ただし、UNKNOWN intentの場合はQAフェーズへ復帰
            intent = context.get("intent", "") if isinstance(context, dict) else ""
            if intent == "UNKNOWN":
                self.logger.warning(f"Exception with UNKNOWN intent, transitioning to QA: {e}")
                return "QA"
            return "NOT_HEARD"
    
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

