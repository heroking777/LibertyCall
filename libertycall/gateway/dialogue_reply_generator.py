"""Reply generation logic extracted from dialogue_engine."""
from __future__ import annotations

import os
from typing import List, Tuple

from .dialogue_flow import get_response as dialogue_get_response
from .prompt_factory import render_templates
from .state_store import get_session_state
from .dialogue_orchestrator import run_conversation_flow
from .dialogue_handoff import handle_handoff_confirm


def generate_reply(core, call_id: str, raw_text: str) -> Tuple[str, List[str], str, bool]:
    state = get_session_state(core, call_id)
    handoff_state = state.handoff_state
    transfer_requested = state.transfer_requested

    dialogue_templates = None
    try:
        if handoff_state != "confirming":
            dialogue_templates, dialogue_phase, dialogue_state = dialogue_get_response(
                user_text=raw_text,
                current_phase=state.phase,
                state={
                    "silence_count": getattr(state, "silence_count", 0),
                    "waiting_retry_count": getattr(state, "waiting_retry_count", 0),
                },
            )

            if dialogue_templates and len(dialogue_templates) > 0:
                core.logger.info(
                    "DIALOGUE_FLOW使用: call_id=%s templates=%s phase=%s->%s",
                    call_id,
                    dialogue_templates,
                    state.phase,
                    dialogue_phase,
                )

                state.phase = dialogue_phase
                for key, value in dialogue_state.items():
                    setattr(state, key, value)

                template_ids = dialogue_templates
                intent = "DIALOGUE_FLOW"
                reply_text = render_templates(template_ids)
                state.last_intent = intent
                return reply_text, template_ids, intent, False

    except Exception as exc:
        core.logger.error(
            "DIALOGUE_FLOW エラー: call_id=%s, error=%s",
            call_id,
            exc,
            exc_info=True,
        )
        dialogue_templates = None

    core.logger.warning(
        "DIALOGUE_FLOW未対応: call_id=%s text=%r handoff_state=%s",
        call_id,
        raw_text,
        handoff_state,
    )

    if handoff_state == "confirming":
        intent = "UNKNOWN"
    else:
        intent = "UNKNOWN"
        template_ids = ["114"]
        reply_text = render_templates(template_ids)
        state.last_intent = intent
        return reply_text, template_ids, intent, False

    if intent == "HANDOFF_REQUEST" and not getattr(core, "transfer_callback", None):
        core.logger.warning(
            "[HANDOFF_UNAVAILABLE] call_id=%s intent=%s transfer_callback=missing",
            call_id or "GLOBAL_CALL",
            intent,
        )
        state.handoff_state = "idle"
        state.handoff_retry_count = 0
        state.handoff_prompt_sent = False
        state.transfer_requested = False
        state.transfer_executed = False
        state.phase = "QA"
        template_ids = ["0605"]
        state.meta["handoff_unavailable"] = True
        state.meta["handoff_alternative_offered"] = True
        reply_text = render_templates(template_ids)
        state.last_intent = "INQUIRY"
        return reply_text, template_ids, "HANDOFF_UNAVAILABLE", False

    if handoff_state == "done" and not state.transfer_requested:
        template_ids, base_intent, transfer_requested = run_conversation_flow(
            core, call_id, raw_text
        )
        template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
        reply_text = render_templates(template_ids)
        core.logger.debug(
            "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
            call_id or "GLOBAL_CALL",
            intent,
            base_intent,
            template_ids,
            state.phase,
            state.handoff_state,
            state.not_heard_streak,
        )
        return reply_text, template_ids, base_intent, transfer_requested

    if handoff_state == "confirming":
        reply_text, template_ids, result_intent, transfer_requested = handle_handoff_confirm(
            core, call_id, raw_text, intent, state
        )
        core.logger.debug(
            "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
            call_id or "GLOBAL_CALL",
            intent,
            result_intent,
            template_ids,
            state.phase,
            state.handoff_state,
            state.not_heard_streak,
        )
        return reply_text, template_ids, result_intent, transfer_requested

    if intent == "UNKNOWN" and handoff_state == "idle" and not state.handoff_prompt_sent:
        state.handoff_state = "confirming"
        state.handoff_retry_count = 0
        state.handoff_prompt_sent = True
        state.transfer_requested = False
        template_ids = ["0604"]
        reply_text = render_templates(template_ids)
        core.logger.debug(
            "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
            call_id or "GLOBAL_CALL",
            intent,
            "UNKNOWN",
            template_ids,
            state.phase,
            state.handoff_state,
            state.not_heard_streak,
        )
        return reply_text, template_ids, "UNKNOWN", False

    template_ids, base_intent, transfer_requested = run_conversation_flow(
        core, call_id, raw_text
    )
    if "0604" in template_ids and "104" in template_ids:
        template_ids = [tid for tid in template_ids if tid != "104"]

    template_ids, intent, should_return_early = core._mis_guard.handle_not_heard_streak(
        call_id, state, template_ids, intent, base_intent
    )
    if should_return_early:
        reply_text = render_templates(template_ids)
        return reply_text, template_ids, base_intent, transfer_requested

    core._mis_guard.handle_unclear_streak(call_id, state, template_ids)

    question_intents = [
        "PRICE",
        "SYSTEM_INQUIRY",
        "FUNCTION",
        "SUPPORT",
        "AI_IDENTITY",
        "SYSTEM_EXPLAIN",
        "RESERVATION",
        "MULTI_STORE",
        "DIALECT",
        "CALLBACK_REQUEST",
        "SETUP_DIFFICULTY",
        "AI_CALL_TOPIC",
        "SETUP",
    ]
    answer_templates = [
        "040",
        "041",
        "042",
        "043",
        "044",
        "045",
        "046",
        "047",
        "048",
        "049",
        "020",
        "021",
        "022",
        "023",
        "023_AI_IDENTITY",
        "024",
        "025",
        "026",
        "060",
        "061",
        "062",
        "063",
        "064",
        "065",
        "066",
        "067",
        "068",
        "069",
        "070",
        "071",
        "072",
        "0600",
        "0601",
        "0603",
        "0280",
        "0281",
        "0282",
        "0283",
        "0284",
        "0285",
    ]

    if (
        base_intent in question_intents
        and "085" not in template_ids
        and state.phase != "AFTER_085"
        and base_intent
        not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO", "END_CALL")
        and template_ids
        and any(tid in answer_templates for tid in template_ids)
    ):
        template_ids.append("085")
        state.phase = "AFTER_085"
        core.logger.debug(
            "[NLG_DEBUG] Added 085 after answer intent: call_id=%s intent=%s tpl=%s phase=%s",
            call_id or "GLOBAL_CALL",
            base_intent,
            template_ids,
            state.phase,
        )

    reply_text = render_templates(template_ids)

    key = call_id or "GLOBAL_CALL"
    if "086" in template_ids and "087" in template_ids:
        if core.hangup_callback:
            force_immediate_hangup = (
                os.getenv("LC_FORCE_IMMEDIATE_HANGUP", "0") == "1"
            )
            if force_immediate_hangup:
                core.logger.info(
                    "DEBUG_FORCE_HANGUP: call_id=%s (immediate, no timer)",
                    key,
                )
                try:
                    core.hangup_callback(key)
                except Exception as exc:
                    core.logger.exception(
                        "DEBUG_FORCE_HANGUP_ERROR: call_id=%s error=%r",
                        key,
                        exc,
                    )
            else:
                core.logger.info(
                    "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                    key,
                )
                try:
                    core._schedule_auto_hangup(key, delay_sec=60.0)
                except Exception as exc:
                    core.logger.exception(
                        "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                        key,
                        exc,
                    )
        else:
            core.logger.warning(
                "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                key,
            )

    core.logger.debug(
        "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
        call_id or "GLOBAL_CALL",
        intent,
        base_intent,
        template_ids,
        state.phase,
        state.handoff_state,
        state.not_heard_streak,
    )

    core.logger.info(
        "GENERATE_REPLY_EXIT: call_id=%s intent=%s base_intent=%s tpl=%s phase=%s has_086_087=%s",
        call_id or "GLOBAL_CALL",
        intent,
        base_intent,
        template_ids,
        state.phase,
        "086" in template_ids and "087" in template_ids,
    )

    return reply_text, template_ids, base_intent, transfer_requested
