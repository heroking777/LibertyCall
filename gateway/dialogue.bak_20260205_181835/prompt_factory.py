"""Template rendering helpers extracted from AICore."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..common.text_utils import get_response_template


def render_templates_from_ids(
    templates: dict,
    template_ids: List[str],
    client_id: Optional[str],
    default_client_id: Optional[str],
    logger,
) -> str:
    effective_client_id = client_id or default_client_id or "000"
    texts: List[str] = []

    for template_id in template_ids:
        template_config = None

        if client_id and client_id != default_client_id:
            try:
                client_templates_path = f"/opt/libertycall/config/clients/{client_id}/templates.json"
                if Path(client_templates_path).exists():
                    with open(client_templates_path, "r", encoding="utf-8") as handle:
                        import json

                        client_templates = json.load(handle)
                        template_config = client_templates.get(template_id)
            except Exception as exc:
                logger.debug("Failed to load client templates for %s: %s", client_id, exc)

        if not template_config:
            template_config = templates.get(template_id) if templates else None

        if template_config and isinstance(template_config, dict):
            text = template_config.get("text", "")
            if text:
                texts.append(text)
        else:
            try:
                text = get_response_template(template_id)
                if text:
                    texts.append(text)
            except Exception:
                pass

    return " ".join(texts) if texts else ""


def render_templates(template_ids: List[str]) -> str:
    texts: List[str] = []
    for template_id in template_ids:
        template_text = get_response_template(template_id)
        if template_text:
            texts.append(template_text)
    return " ".join(texts).strip()
