"""Event routing for gateway network handlers."""
from __future__ import annotations

import asyncio
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional

from libertycall.client_loader import load_client_profile

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


class GatewayEventRouter:
    def __init__(self, gateway: "RealtimeGateway") -> None:
        self.gateway = gateway
        self.logger = gateway.logger

    async def handle_control_message(self, data: Dict[str, Any]) -> bool:
        """Handle control-plane websocket messages."""
        gateway = self.gateway
        msg_type = data.get("type")

        if msg_type == "init":
            try:
                req_client_id = data.get("client_id")
                req_call_id = data.get("call_id")
                req_caller_number = data.get("caller_number")
                self.logger.debug("[Init] Request for client_id: %s", req_client_id)

                gateway.client_profile = load_client_profile(req_client_id)

                if gateway.call_id and (
                    gateway.client_id != req_client_id
                    or (req_call_id and gateway.call_id != req_call_id)
                ):
                    gateway._complete_console_call()
                gateway._reset_call_state()
                gateway.client_id = req_client_id
                gateway.config = gateway.client_profile["config"]
                gateway.rules = gateway.client_profile["rules"]

                if hasattr(gateway.ai_core, "set_client_id"):
                    gateway.ai_core.set_client_id(req_client_id)
                elif hasattr(gateway.ai_core, "client_id"):
                    gateway.ai_core.client_id = req_client_id
                    if hasattr(gateway.ai_core, "reload_flow"):
                        gateway.ai_core.reload_flow()

                if req_caller_number:
                    gateway.ai_core.caller_number = req_caller_number
                    self.logger.debug(
                        "[Init] Set caller_number: %s", req_caller_number
                    )
                else:
                    gateway.ai_core.caller_number = None
                    self.logger.debug(
                        "[Init] caller_number not provided in init message"
                    )

                gateway._ensure_console_session(call_id_override=req_call_id)
                task = asyncio.create_task(
                    gateway._queue_initial_audio_sequence(gateway.client_id)
                )

                def _log_init_task_result(t: asyncio.Task) -> None:
                    try:
                        t.result()
                    except Exception as e:
                        self.logger.error(
                            "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                            e,
                            traceback.format_exc(),
                        )

                task.add_done_callback(_log_init_task_result)
                self.logger.warning(
                    "[INIT_TASK_START] Created task for %s", gateway.client_id
                )

                self.logger.debug(
                    "[Init] Loaded: %s", gateway.config.get("client_name")
                )
            except Exception as e:
                self.logger.debug("[Init Error] %s", e)
            return True

        if msg_type == "call_end":
            try:
                req_call_id = data.get("call_id")
                if req_call_id and gateway.call_id == req_call_id:
                    gateway._stop_recording()
                    gateway._complete_console_call()
            except Exception as e:
                self.logger.error("call_end handling failed: %s", e)
            return True

        return False

    async def handle_asterisk_message(self, data: Dict[str, Any]) -> bool:
        msg_type = data.get("type")
        if msg_type == "init":
            self.logger.info("[WS Server] INIT from Asterisk: %s", data)
            await self.gateway._handle_init_from_asterisk(data)
            return True
        return False

    async def handle_event_socket_message(
        self, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        gateway = self.gateway
        event_type = message.get("event")
        uuid = message.get("uuid")
        call_id = message.get("call_id")
        client_id = message.get("client_id", "000")

        self.logger.info(
            "[EVENT_SOCKET] Received event: %s uuid=%s call_id=%s",
            event_type,
            uuid,
            call_id,
        )

        if event_type == "call_start":
            if call_id:
                effective_call_id = call_id
            elif uuid:
                effective_call_id = gateway._generate_call_id_from_uuid(uuid, client_id)
            else:
                self.logger.warning(
                    "[EVENT_SOCKET] call_start event missing call_id and uuid"
                )
                return {
                    "status": "error",
                    "message": "missing call_id or uuid",
                }

            if uuid and effective_call_id:
                gateway.call_uuid_map[effective_call_id] = uuid
                self.logger.info(
                    "[EVENT_SOCKET] Mapped call_id=%s -> uuid=%s",
                    effective_call_id,
                    uuid,
                )

            try:
                if hasattr(gateway.ai_core, "on_call_start"):
                    gateway.ai_core.on_call_start(
                        effective_call_id, client_id=client_id
                    )
                    self.logger.info(
                        "[EVENT_SOCKET] on_call_start() called for call_id=%s client_id=%s",
                        effective_call_id,
                        client_id,
                    )
                else:
                    self.logger.error(
                        "[EVENT_SOCKET] ai_core.on_call_start() not found"
                    )
            except Exception as e:
                self.logger.exception(
                    "[EVENT_SOCKET] Error calling on_call_start(): %s",
                    e,
                )

            self.logger.warning(
                "[CALL_START_TRACE] [LOC_START] Adding %s to _active_calls (event_socket) at %.3f",
                effective_call_id,
                time.time(),
            )
            gateway._active_calls.add(effective_call_id)
            gateway.call_id = effective_call_id
            gateway.client_id = client_id
            self.logger.info(
                "[EVENT_SOCKET] Added call_id=%s to _active_calls, set call_id and client_id=%s",
                effective_call_id,
                client_id,
            )

            try:
                task = asyncio.create_task(
                    gateway._queue_initial_audio_sequence(client_id)
                )

                def _log_init_task_result(t: asyncio.Task) -> None:
                    try:
                        t.result()
                    except Exception as e:
                        self.logger.error(
                            "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                            e,
                            traceback.format_exc(),
                        )

                task.add_done_callback(_log_init_task_result)
                self.logger.warning(
                    "[INIT_TASK_START] Created task for %s", client_id
                )
                self.logger.info(
                    "[EVENT_SOCKET] _queue_initial_audio_sequence() called for call_id=%s client_id=%s",
                    effective_call_id,
                    client_id,
                )
            except Exception as e:
                self.logger.exception(
                    "[EVENT_SOCKET] Error calling _queue_initial_audio_sequence(): %s",
                    e,
                )

            return {"status": "ok"}

        if event_type == "call_end":
            effective_call_id: Optional[str] = None
            try:
                if call_id:
                    effective_call_id = call_id
                elif uuid:
                    for cid, u in gateway.call_uuid_map.items():
                        if u == uuid:
                            effective_call_id = cid
                            break

                    if not effective_call_id:
                        self.logger.warning(
                            "[EVENT_SOCKET] call_end event: uuid=%s not found in call_uuid_map",
                            uuid,
                        )
                        return {"status": "error", "message": "uuid not found"}
                else:
                    self.logger.warning(
                        "[EVENT_SOCKET] call_end event missing call_id and uuid"
                    )
                    return {
                        "status": "error",
                        "message": "missing call_id or uuid",
                    }

                try:
                    if hasattr(gateway.ai_core, "on_call_end"):
                        gateway.ai_core.on_call_end(
                            effective_call_id, source="gateway_event_listener"
                        )
                        self.logger.info(
                            "[EVENT_SOCKET] on_call_end() called for call_id=%s",
                            effective_call_id,
                        )
                    else:
                        self.logger.error(
                            "[EVENT_SOCKET] ai_core.on_call_end() not found"
                        )
                    if hasattr(gateway.ai_core, "cleanup_asr_instance"):
                        gateway.ai_core.cleanup_asr_instance(effective_call_id)
                        self.logger.info(
                            "[EVENT_SOCKET] cleanup_asr_instance() called for call_id=%s",
                            effective_call_id,
                        )
                except Exception as e:
                    self.logger.exception(
                        "[EVENT_SOCKET] Error calling on_call_end(): %s",
                        e,
                    )

                if gateway.call_id == effective_call_id:
                    gateway.call_id = None

                if effective_call_id in gateway.call_uuid_map:
                    del gateway.call_uuid_map[effective_call_id]

                return {"status": "ok"}
            except Exception as e:
                self.logger.error(
                    "[EVENT_SOCKET_ERR] Error during call_end processing for call_id=%s: %s",
                    effective_call_id,
                    e,
                    exc_info=True,
                )
                return {"status": "error", "message": "internal error"}
            finally:
                self.logger.warning(
                    "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                    effective_call_id,
                )
                if effective_call_id:
                    call_end_time = time.time()
                    self.logger.warning(
                        "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                        effective_call_id,
                        effective_call_id in gateway._active_calls
                        if hasattr(gateway, "_active_calls")
                        else False,
                    )
                    if (
                        hasattr(gateway, "_active_calls")
                        and effective_call_id in gateway._active_calls
                    ):
                        gateway._active_calls.remove(effective_call_id)
                        self.logger.warning(
                            "[EVENT_SOCKET_DONE] Removed %s from active_calls (finally block) at %.3f",
                            effective_call_id,
                            call_end_time,
                        )
                    self.logger.warning(
                        "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                        effective_call_id,
                        effective_call_id in gateway._active_calls
                        if hasattr(gateway, "_active_calls")
                        else False,
                    )

                    if effective_call_id in gateway._recovery_counts:
                        del gateway._recovery_counts[effective_call_id]
                    if effective_call_id in gateway._initial_sequence_played:
                        gateway._initial_sequence_played.discard(effective_call_id)
                    if effective_call_id in gateway._last_processed_sequence:
                        del gateway._last_processed_sequence[effective_call_id]
                    gateway._last_voice_time.pop(effective_call_id, None)
                    gateway._last_silence_time.pop(effective_call_id, None)
                    gateway._last_tts_end_time.pop(effective_call_id, None)
                    gateway._last_user_input_time.pop(effective_call_id, None)
                    gateway._silence_warning_sent.pop(effective_call_id, None)
                    if hasattr(gateway, "_initial_tts_sent"):
                        gateway._initial_tts_sent.discard(effective_call_id)
                    self.logger.debug(
                        "[CALL_CLEANUP] Cleared state for call_id=%s",
                        effective_call_id,
                    )

        self.logger.warning("[EVENT_SOCKET] Unknown event type: %s", event_type)
        return {"status": "error", "message": "unknown event type"}
