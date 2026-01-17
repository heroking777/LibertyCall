"""Activity monitor logic extracted from AICore."""

from __future__ import annotations

import logging
import time


def start_activity_monitor(core) -> None:
    if core._activity_monitor_running:
        return

    def _activity_monitor_worker() -> None:
        core._activity_monitor_running = True
        core.logger.info("[ACTIVITY_MONITOR] Started activity monitor thread")

        while core._activity_monitor_running:
            try:
                time.sleep(1.0)

                current_time = time.time()
                timeout_sec = 10.0

                active_call_ids = set()
                if hasattr(core, "gateway") and hasattr(core.gateway, "_active_calls"):
                    active_call_ids = set(core.gateway._active_calls) if core.gateway._active_calls else set()

                for call_id, last_activity_time in list(core.last_activity.items()):
                    if active_call_ids and call_id not in active_call_ids:
                        core.logger.info("[ACTIVITY_MONITOR] Skipping inactive call: call_id=%s", call_id)
                        continue

                    if core.is_playing.get(call_id, False):
                        continue

                    elapsed = current_time - last_activity_time
                    if elapsed >= timeout_sec:
                        core.logger.info(
                            "[ACTIVITY_MONITOR] Timeout detected: call_id=%s elapsed=%.1fs -> calling FlowEngine.transition(NOT_HEARD)",
                            call_id,
                            elapsed,
                        )

                        try:
                            flow_engine = core.flow_engines.get(call_id) or core.flow_engine
                            if flow_engine:
                                state = core._get_session_state(call_id)
                                client_id = (
                                    core.call_client_map.get(call_id)
                                    or state.meta.get("client_id")
                                    or core.client_id
                                    or "000"
                                )

                                context = {
                                    "intent": "NOT_HEARD",
                                    "text": "",
                                    "normalized_text": "",
                                    "keywords": core.keywords,
                                    "user_reply_received": False,
                                    "user_voice_detected": False,
                                    "timeout": True,
                                    "is_first_sales_call": getattr(state, "is_first_sales_call", False),
                                }

                                next_phase = flow_engine.transition(state.phase or "ENTRY", context)

                                if next_phase != state.phase:
                                    state.phase = next_phase
                                    core.logger.info(
                                        "[ACTIVITY_MONITOR] Phase transition: %s -> %s (call_id=%s, timeout)",
                                        state.phase,
                                        next_phase,
                                        call_id,
                                    )

                                template_ids = flow_engine.get_templates(next_phase)
                                if template_ids:
                                    core._play_template_sequence(call_id, template_ids, client_id)

                                    if next_phase == "NOT_HEARD" and "110" in template_ids:
                                        state.phase = "QA"
                                        core.logger.info(
                                            "[ACTIVITY_MONITOR] NOT_HEARD (110) played, transitioning to QA: call_id=%s",
                                            call_id,
                                        )
                                        runtime_logger = logging.getLogger("runtime")
                                        runtime_logger.info(
                                            "[FLOW] call_id=%s phase=NOT_HEARD→QA intent=NOT_HEARD template=110 (timeout recovery)",
                                            call_id,
                                        )
                        except Exception as exc:
                            core.logger.exception("[ACTIVITY_MONITOR] Error handling timeout: %s", exc)
            except Exception as exc:
                if core._activity_monitor_running:
                    core.logger.exception("[ACTIVITY_MONITOR] Monitor thread error: %s", exc)
                time.sleep(1.0)

    import threading

    core._activity_monitor_thread = threading.Thread(target=_activity_monitor_worker, daemon=True)
    core._activity_monitor_thread.start()
    core.logger.info("[ACTIVITY_MONITOR] Activity monitor thread started")
