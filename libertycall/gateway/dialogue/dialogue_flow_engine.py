"""FlowEngine transition helpers for dialogue handling."""
from __future__ import annotations

from typing import List, Tuple

from .prompt_factory import render_templates_from_ids
from .flow_engine import FlowEngine


def handle_flow_engine_transition(
    core,
    call_id: str,
    text: str,
    normalized_text: str,
    intent: str,
    state,
    flow_engine: FlowEngine,
    client_id: str,
) -> Tuple[str, List[str], str, bool]:
    current_phase = state.phase or "ENTRY"

    context = {
        "intent": intent or "UNKNOWN",
        "text": text,
        "normalized_text": normalized_text,
        "keywords": core.keywords,
        "user_reply_received": bool(text and len(text.strip()) > 0),
        "user_voice_detected": bool(text and len(text.strip()) > 0),
        "timeout": False,
        "is_first_sales_call": getattr(state, "is_first_sales_call", False),
    }

    next_phase = flow_engine.transition(current_phase, context)

    if next_phase != current_phase:
        state.phase = next_phase
        core.logger.info(
            "[FLOW_ENGINE] Phase transition: %s -> %s (call_id=%s, client_id=%s, intent=%s)",
            current_phase,
            next_phase,
            call_id,
            client_id,
            intent,
        )

    if current_phase == "ENTRY" and next_phase != "ENTRY":
        template_ids = flow_engine.get_templates(current_phase)
        core.logger.info(
            "[FLOW_ENGINE] Using ENTRY phase templates for transition: %s -> %s",
            current_phase,
            next_phase,
        )
    else:
        template_ids = flow_engine.get_templates(next_phase)

    if not template_ids:
        template_ids = flow_engine.get_templates(current_phase)

    if template_ids and len(template_ids) > 1:
        try:
            template_ids = [template_ids[0]]
        except Exception as exc:
            core.logger.warning(
                "[FLOW_ENGINE] Failed to select template: %s, using first template",
                exc,
            )
            template_ids = [template_ids[0]]
    elif not template_ids:
        template_ids = ["110"]

    reply_text = (
        render_templates_from_ids(
            core.templates,
            template_ids,
            client_id,
            core.client_id,
            core.logger,
        )
        if template_ids
        else ""
    )

    transfer_requested = next_phase == "HANDOFF_DONE"

    return reply_text, template_ids, intent, transfer_requested
