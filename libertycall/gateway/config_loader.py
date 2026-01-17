"""Config loading helpers extracted from AICore."""

from __future__ import annotations

import json
import os


def load_flow(core, client_id: str) -> dict:
    path = f"/opt/libertycall/config/clients/{client_id}/flow.json"
    default_path = "/opt/libertycall/config/system/default_flow.json"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            flow = json.load(handle)
            version = flow.get("version", "unknown")
            core.logger.info("[FLOW] client=%s version=%s loaded", client_id, version)
            return flow

    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as handle:
            flow = json.load(handle)
            core.logger.warning(
                "[FLOW] client=%s missing, loaded default version=%s",
                client_id,
                flow.get("version", "unknown"),
            )
            return flow

    core.logger.error("[FLOW] client=%s missing and default not found, using empty flow", client_id)
    return {}


def load_json(core, path: str, default: str = None) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    if default and os.path.exists(default):
        with open(default, "r", encoding="utf-8") as handle:
            core.logger.debug("[FLOW] Using default file: %s", default)
            return json.load(handle)
    return {}


def load_keywords_from_config(core) -> None:
    if not core.keywords:
        core.logger.warning("[FLOW] keywords not loaded, using empty lists")
        core.AFTER_085_NEGATIVE_KEYWORDS = []
        core.ENTRY_TRIGGER_KEYWORDS = []
        core.CLOSING_YES_KEYWORDS = []
        core.CLOSING_NO_KEYWORDS = []
        return

    core.AFTER_085_NEGATIVE_KEYWORDS = core.keywords.get("AFTER_085_NEGATIVE_KEYWORDS", [])
    core.ENTRY_TRIGGER_KEYWORDS = core.keywords.get("ENTRY_TRIGGER_KEYWORDS", [])
    core.CLOSING_YES_KEYWORDS = core.keywords.get("CLOSING_YES_KEYWORDS", [])
    core.CLOSING_NO_KEYWORDS = core.keywords.get("CLOSING_NO_KEYWORDS", [])

    core.logger.debug(
        "[FLOW] Keywords loaded: ENTRY_TRIGGER=%s, CLOSING_YES=%s, CLOSING_NO=%s, AFTER_085_NEGATIVE=%s",
        len(core.ENTRY_TRIGGER_KEYWORDS),
        len(core.CLOSING_YES_KEYWORDS),
        len(core.CLOSING_NO_KEYWORDS),
        len(core.AFTER_085_NEGATIVE_KEYWORDS),
    )
