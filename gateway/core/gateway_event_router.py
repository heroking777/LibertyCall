"""Event routing for gateway network handlers."""
from __future__ import annotations

import asyncio
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional

def _safe_get(mapping: Optional[Dict[str, Any]], key: str, default: str = "") -> str:
    try:
        value = mapping.get(key, default) if isinstance(mapping, dict) else default
    except Exception:
        value = default
    return "" if value is None else str(value)

from client_loader import load_client_profile

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from ..realtime_gateway import RealtimeGateway


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
        # [PATCH] Entry point debug & force dispatch (Smart)
        try:
            _evt_val = message.get("event") or message.get("type")
            self.logger.info("[GW_ROUTER_ENTRY] keys=%s, event=%r", list(message.keys()), _evt_val)
            if _evt_val and str(_evt_val).strip() == "fs_evt":
                self.logger.info("[GW_FSEVT_FORCE] Force handling fs_evt at entry")
                if hasattr(self, "handle_fs_evt"):
                    import inspect
                    if inspect.iscoroutinefunction(self.handle_fs_evt):
                        await self.handle_fs_evt(message)
                    else:
                        self.handle_fs_evt(message)
                    return
        except Exception as e:
            self.logger.error("[GW_ROUTER_ENTRY_ERR] %s", e)

        gateway = self.gateway
        event_type = message.get("event")

        # [PATCH] Force fs_evt dispatch (High Priority)
        # Debug: check what exactly is in the variable
        if "event_type" in locals():
            _evt_raw = str(event_type) if event_type is not None else ""
            if _evt_raw.strip() == "fs_evt":
                self.logger.info("[GW_FSEVT_ROUTE] Force dispatching fs_evt. Raw: %r", event_type)
                if hasattr(self, "handle_fs_evt"):
                    import inspect
                    _msg = locals().get("message") or locals().get("msg") or {}
                    if inspect.iscoroutinefunction(self.handle_fs_evt):
                        await self.handle_fs_evt(_msg)
                    else:
                        self.handle_fs_evt(_msg)
                    return
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

        if event_type == "fs_evt":
            await self.handle_fs_evt(message)
            return {"status": "ok"}


        # [PATCH] Dispatch fs_evt explicitly
        if event_type == "fs_evt":
            self.logger.info("[GW_FSEVT_ROUTE] Dispatching fs_evt to handle_fs_evt")
            if hasattr(self, "handle_fs_evt"):
                # Try await if it is a coroutine
                import inspect
                if inspect.iscoroutinefunction(self.handle_fs_evt):
                    await self.handle_fs_evt(message)
                else:
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.handle_fs_evt, message
                    )
                return
            else:
                self.logger.error("[GW_FSEVT_ROUTE] handle_fs_evt method missing!")
                return
        self.logger.warning("[EVENT_SOCKET] Unknown event type: %s", event_type)
        return {"status": "error", "message": "unknown event type"}

    async def handle_fs_evt(self, payload: Dict[str, Any]) -> None:
        uuid = _safe_get(payload, "uuid") or _safe_get(payload, "Unique-ID")
        name = _safe_get(payload, "Event-Name") or _safe_get(payload, "name")
        app = _safe_get(payload, "app")
        data = _safe_get(payload, "data")
        call_id = uuid or _safe_get(payload, "call_id")

        self.logger.info(
            "[GW_FSEVT_RX] call_id=%s event=%s app=%s data=%s",
            call_id,
            name,
            app,
            data,
        )

        if not name:
            self.logger.warning("[GW_FSEVT_RX] Event-Name missing; skipping")
            return

        try:
            if call_id and name == "CHANNEL_ANSWER":
                await self._start_asr_session(call_id, payload)
            elif call_id and name in {"CHANNEL_HANGUP", "CHANNEL_DESTROY", "CHANNEL_HANGUP_COMPLETE"}:
                await self._stop_asr_session(call_id)
        except Exception:
            self.logger.exception("[GW_FSEVT_ASR_CTRL_ERR] call_id=%s event=%s", call_id, name)

        action = "ignore"
        reason = "no_route"

        if name in {"PLAYBACK_START", "PLAYBACK_STOP", "PLAYBACK_PAUSE", "PLAYBACK_RESUME"}:
            action = "update_playback_state"
            reason = "playback_event"
        elif name in {"MEDIA_BUG_START", "MEDIA_BUG_STOP"}:
            action = "update_media_bug_state"
            reason = "media_bug_event"
        elif name in {"CHANNEL_EXECUTE", "CHANNEL_EXECUTE_COMPLETE"}:
            action = "update_channel_execute_state"
            reason = "channel_execute"
        elif name in {"CHANNEL_HANGUP", "CHANNEL_DESTROY", "CHANNEL_HANGUP_COMPLETE"}:
            action = "update_call_end_state"
            reason = "hangup_destroy"
        else:
            action = "ignore"
            reason = "unhandled_name"

        self.logger.info(
            "[GW_FSEVT_ROUTE] call_id=%s action=%s reason=%s",
            call_id,
            action,
            reason,
        )

        try:
            if action == "update_playback_state":
                return
            if action == "update_media_bug_state":
                return
            if action == "update_channel_execute_state":
                return
            if action == "update_call_end_state":
                return
        except Exception:
            self.logger.exception(
                "[GW_FSEVT_ERR] call_id=%s event=%s app=%s", call_id, name, app
            )

    async def _start_asr_session(self, call_id: str, event_data: Dict[str, Any]) -> None:
        self.logger.info("[GW_ROUTER_ASR_START] call_id=%s", call_id)
        asr_manager = getattr(self.gateway, "asr_manager", None)
        if not (asr_manager and hasattr(asr_manager, "start_asr_for_call")):
            self.logger.warning("[GW_ROUTER_ASR_START] ASR manager unavailable for %s", call_id)
            return

        additional_keys = {
            "Channel-Name",
            "Channel-State",
            "Answer-State",
            "Caller-Caller-ID-Number",
            "Caller-Destination-Number",
        }
        channel_vars = {
            key: value
            for key, value in event_data.items()
            if key.startswith("variable_") or key in additional_keys
        }

        # ===== デバッグログ追加（Phase2確認用） =====
        self.logger.info(f"🔍 [DEBUG] Channel vars for {call_id}:")

        rtp_related_keys = [
            key for key in channel_vars.keys()
            if any(token in key.lower() for token in ("media", "rtp", "codec", "ssrc"))
        ]

        if rtp_related_keys:
            for key in sorted(rtp_related_keys):
                self.logger.info("  %s = %s", key, channel_vars.get(key))
        else:
            self.logger.warning("  ⚠️ No RTP-related variables found!")
            preview_keys = list(channel_vars.keys())[:10]
            self.logger.info("  Available keys: %s%s",
                             preview_keys,
                             "..." if len(channel_vars) > len(preview_keys) else "")
        # ===== デバッグログ終了 =====

        if channel_vars:
            self.logger.debug(
                "[GW_ROUTER_ASR_VARS] call_id=%s keys=%s",
                call_id,
                list(channel_vars.keys()),
            )

        required_vars = ["variable_remote_media_ip", "variable_remote_media_port"]
        missing_vars = [var for var in required_vars if var not in channel_vars]
        if missing_vars:
            self.logger.warning(
                "[GW_ROUTER_ASR_VARS_MISSING] call_id=%s missing=%s",
                call_id,
                missing_vars,
            )

        try:
            result = asr_manager.start_asr_for_call(call_id, channel_vars)
            if asyncio.iscoroutine(result):
                result = await result
            if not result:
                self.logger.error(
                    "[GW_ROUTER_ASR_START_ERR] ASR manager rejected call_id=%s",
                    call_id,
                )
                return
        except Exception:
            self.logger.exception("[GW_ROUTER_ASR_START_ERR] call_id=%s", call_id)
            return

        ai_core = getattr(self.gateway, "ai_core", None)
        if ai_core and hasattr(ai_core, "on_call_start"):
            try:
                result = ai_core.on_call_start(call_id, client_id=event_data.get("Client-ID"))
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self.logger.exception("[GW_ROUTER_AI_START_ERR] call_id=%s", call_id)

    async def _stop_asr_session(self, call_id: str) -> None:
        self.logger.info("[GW_ROUTER_ASR_STOP] call_id=%s", call_id)
        asr_manager = getattr(self.gateway, "asr_manager", None)
        if asr_manager and hasattr(asr_manager, "stop_asr_for_call"):
            try:
                result = asr_manager.stop_asr_for_call(call_id)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self.logger.exception("[GW_ROUTER_ASR_STOP_ERR] call_id=%s", call_id)
        else:
            self.logger.warning("[GW_ROUTER_ASR_STOP] ASR manager unavailable for %s", call_id)
