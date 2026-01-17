"""Flow reload helpers extracted from AICore."""

from __future__ import annotations


def reload_flow(core) -> None:
    core.flow = core._load_flow(core.client_id)
    core.templates = core._load_json(
        f"/opt/libertycall/config/clients/{core.client_id}/templates.json",
        default="/opt/libertycall/config/system/default_templates.json",
    )
    core.keywords = core._load_json(
        f"/opt/libertycall/config/clients/{core.client_id}/keywords.json",
        default="/opt/libertycall/config/system/default_keywords.json",
    )
    core._load_keywords_from_config()
    core.logger.info("[FLOW] reloaded for client=%s", core.client_id)
