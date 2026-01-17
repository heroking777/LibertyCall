"""Flow definition loader utilities (YAML/JSON)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


class FlowDefinitionError(RuntimeError):
    """Raised when a flow definition file is invalid."""


def _validate_flow_definition(data: Dict[str, Any], logger: logging.Logger) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise FlowDefinitionError("Flow definition must be a mapping")
    nodes = data.get("nodes")
    if nodes is not None and not isinstance(nodes, dict):
        logger.warning("Flow definition 'nodes' should be a mapping")
    return data


def load_flow_definition(path: str, logger: logging.Logger) -> Dict[str, Any]:
    """Load a flow definition from YAML/JSON."""
    file_path = Path(path)
    if not file_path.exists():
        raise FlowDefinitionError(f"Flow definition not found: {path}")

    suffix = file_path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise FlowDefinitionError("PyYAML is not installed")
            with file_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        else:
            with file_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
    except Exception as exc:  # pragma: no cover - load errors
        raise FlowDefinitionError(f"Failed to load flow definition: {exc}") from exc

    return _validate_flow_definition(data, logger)
