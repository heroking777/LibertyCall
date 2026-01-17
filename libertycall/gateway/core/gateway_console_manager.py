"""Console bridge helpers for RealtimeGateway."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


class GatewayConsoleManager:
    def __init__(self, gateway: "RealtimeGateway") -> None:
        self.gateway = gateway
        self.logger = gateway.logger

    def ensure_console_session(self, call_id_override: Optional[str] = None) -> None:
        """コンソールセッションを確保（call_idが未設定の場合は正式なcall_idを生成）"""
        gateway = self.gateway
        if not gateway.console_bridge.enabled:
            return
        if not gateway.client_id:
            return

        if call_id_override:
            if gateway.call_id and gateway.call_id != call_id_override:
                self.logger.info(
                    "Call ID override: keeping original call_id=%s, new=%s",
                    gateway.call_id,
                    call_id_override,
                )
                return
            gateway.call_id = call_id_override
        elif not gateway.call_id:
            gateway.call_id = gateway.console_bridge.issue_call_id(gateway.client_id)
            self.logger.info("Generated new call_id: %s", gateway.call_id)

        self.logger.debug("Console session started: %s", gateway.call_id)

        if gateway.call_id:
            gateway.ai_core.set_call_id(gateway.call_id)
        if gateway.client_id:
            gateway.ai_core.client_id = gateway.client_id

        if gateway.call_id and gateway.call_start_time is None:
            gateway.call_start_time = time.time()
            gateway.user_turn_index = 0

        gateway.recent_dialogue.clear()
        gateway.transfer_notified = False
        gateway.call_completed = False
        gateway.current_state = "init"
        caller_number = getattr(gateway.ai_core, "caller_number", None)

        self.logger.info(
            "[_ensure_console_session] caller_number: %s (call_id=%s)",
            caller_number,
            gateway.call_id,
        )

        gateway.console_bridge.start_call(
            gateway.call_id,
            gateway.client_id,
            state=gateway.current_state,
            started_at=datetime.utcnow(),
            caller_number=caller_number,
        )

    def append_console_log(
        self,
        role: str,
        text: Optional[str],
        state: str,
        template_id: Optional[str] = None,
    ) -> None:
        gateway = self.gateway
        if not gateway.console_bridge.enabled or not text:
            return

        if not gateway.call_id:
            if gateway.client_id:
                gateway.call_id = gateway.console_bridge.issue_call_id(gateway.client_id)
                self.logger.debug("Generated call_id for log: %s", gateway.call_id)
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
            else:
                self.logger.warning("Cannot append log: call_id and client_id are not set")
                return

        caller_number = getattr(gateway.ai_core, "caller_number", None)

        gateway.console_bridge.append_log(
            gateway.call_id,
            role=role,
            text=text,
            state=state,
            client_id=gateway.client_id,
            caller_number=caller_number,
            template_id=template_id,
        )

    def record_dialogue(self, role_label: str, text: Optional[str]) -> None:
        if not text:
            return
        self.gateway.recent_dialogue.append((role_label, text.strip()))

    def build_handover_summary(self, state_label: str) -> str:
        gateway = self.gateway
        lines = ["■ 要件", f"- 推定意図: {state_label or '不明'}", "", "■ 直近の会話"]
        if not gateway.recent_dialogue:
            lines.append("- (直近ログなし)")
        else:
            for role, text in gateway.recent_dialogue:
                lines.append(f"- {role}: {text}")
        return "\n".join(lines)

    def generate_call_id_from_uuid(self, uuid: str, client_id: str) -> str:
        gateway = self.gateway
        if hasattr(gateway, "console_bridge") and gateway.console_bridge:
            call_id = gateway.console_bridge.issue_call_id(client_id)
            self.logger.info(
                "[EVENT_SOCKET] Generated call_id=%s from uuid=%s client_id=%s",
                call_id,
                uuid,
                client_id,
            )
        else:
            call_id = f"in-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.logger.warning(
                "[EVENT_SOCKET] console_bridge not available, using fallback call_id=%s",
                call_id,
            )

        return call_id
